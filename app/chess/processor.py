from app.chess.recognizer import ChessRecognizer
from app.chess.message import Message, MessageType, MessageContent, TurnState
from app.chess.message_bus import message_bus
from app.chess.context import context
from app.chess.checker import BoardStatus
from app.tools import utils
from app.tools.log_config import get_logger
from pprint import pformat
from typing import Tuple, Optional, Dict, Any, List
from dataclasses import dataclass
import threading, queue, time

logger = get_logger(__name__)


@dataclass
class BoardAnalysisState:
    board_array: Optional[list] = None
    board_status: Optional[BoardStatus] = None
    img: Any = None
    marker_coords: Optional[list] = None
    timestamp: float = 0.0
    is_settlement_screen: bool = False  # 结算画面标记

class ChessProcess:

    @classmethod
    def from_context(cls, context): 
        """从全局上下文创建实例"""
        return cls(
            checker=context.get_checker(),
            engine=context.get_engine(),
            history=context.history,
            context=context
        )
   
    def __init__(self, checker, engine, history, context):
        """
        初始化处理器
        Args:
            checker: 局面检查器
            engine: 象棋引擎
            history: 历史记录管理器
            context: 上下文配置
        """
        self.checker = checker
        self.engine  = engine
        self.history = history
        self.context = context
        self.use_startpos = False
        
        # 使用单例 Recognizer 以保持内部缓存
        self.recognizer = self.context.get_recognizer()
        if not self.recognizer:
            self.recognizer = ChessRecognizer(self.context)
            self.context.set_recognizer(self.recognizer)
        
    def _process_image(self, img, capture_time=0.0):
        """主流程入口，处理图像并返回相应消息"""
        # 1. 识别棋盘和棋子 (同时获取标记)
        board, marker_coords, grid_hashes, is_massive_change = self._recognize_pieces(img)
        
        # 2. 结算画面检测 + 棋盘状态检查（都需要加锁保护 checker 状态）
        history_moves = self.history.get_moves_str() if self.history else ""
        with self.context._checker_lock:
            # 2.1 结算画面检测（包括 board=None 的情况）
            if self.checker.check_settlement(board, is_massive_change):
                return BoardAnalysisState(timestamp=capture_time, is_settlement_screen=True)
            
            # 识别失败且不在结算状态，直接返回
            if board is None:
                return BoardAnalysisState(timestamp=capture_time)

            # 2.2 检查棋盘状态
            status = self.checker.check_board(
                board, 
                marker_coords, 
                base_fen=self.context.base_fen,
                history_moves=history_moves
            )
                    
        return BoardAnalysisState(
            board_array=board, 
            board_status=status, 
            img=img, 
            marker_coords=marker_coords,
            timestamp=capture_time
        )
    
    def _recognize_pieces(self, img) -> Optional[list]:
        # 识别棋盘和棋子
        platform = self.context.get_platform(self.context.platform)
        coords = getattr(platform, 'board_coords', {}) or {}
        x_array = coords.get("x", [])
        y_array = coords.get("y", [])

        board_array, marker_coords, grid_hashes, details = self.recognizer.recognize_piece_from_grid(
            img, x_array, y_array
        )
        if hasattr(self.checker, 'normalize_visual_board'):
            board_array = self.checker.normalize_visual_board(
                board_array, grid_hashes, marker_coords, details
            )

        # 处理识别过程中的详情/警告
        is_massive_change = False
        if details:
            from app.chess.recognizer import RecognitionErrorType
            
            # 先检查是否是巨大变化（可能是结算画面）
            is_massive_change = any(d.type == RecognitionErrorType.MASSIVE_CHANGE for d in details)
            
            # 如果是，直接返回，跳过所有错误检查
            if is_massive_change:
                logger.debug("检测到巨大变化，跳过错误检查")
                return board_array, marker_coords, grid_hashes, is_massive_change
            
            # 如果已知处于结算状态，同样跳过所有检查，避免循环重试
            if self.checker.in_settlement_screen:
                logger.debug("处于结算画面中，忽略识别错误")
                return board_array, marker_coords, grid_hashes, is_massive_change

            # 处理其他识别错误 （排除错误中的允许情况，然后集中安排重试）
            fatal_errors = []
            for d in details:
                # 标记只用于辅助验证，棋盘变化才是真相源。新版 JJ 的移动
                # 标记可能短暂消失，因此无标记不能成为丢弃整帧的理由。
                if d.type == RecognitionErrorType.MARKER_MISSING:
                    logger.debug("未检测到移动标记，继续使用棋盘变化判断")
                    continue
                
                # 低置信度格已回退到上一帧（或空格），允许后续校验处理。
                if d.type == RecognitionErrorType.LOW_CONFIDENCE:
                    logger.debug(f"低置信度警告(已使用安全回退): {d.message}")
                    continue
                
                # 其他所有类型错误 (如 COVERED, UNKNOWN, MARKER_MISSING) ，默认丢帧重试
                fatal_errors.append(d)

            if fatal_errors:
                 logger.warning(f"识别结果不可用，丢弃当前帧: {fatal_errors}")
                 # 只要有任何不可忽略的错误，就丢弃帧
                 self.context.discard_before_timestamp = time.time()  # 过滤旧帧
                 message_bus.publish(Message(MessageType.RETRY_CAPTURE, f"画面异常: {len(fatal_errors)}处错误"))
                 return None, [], None, False

        return board_array, marker_coords, grid_hashes, is_massive_change

    def _handle_status(self, state: BoardAnalysisState):
        def callback(msg):
            message_bus.publish(msg)

        # 处理各种不同状态

        # 1. 结算状态
        if state.is_settlement_screen:
            message_bus.publish(Message(MessageType.MOVE_TEXT, ""))  # 清空着法文本
            message_bus.publish(Message(MessageType.NON_GAME_SCREEN, MessageContent.NON_GAME_SCREEN))
            return BoardAnalysisState()
        
        status = state.board_status
        if status is None:
            return BoardAnalysisState()
        
        # 2. 当检测到明确有效可接受的变化时，重置连续丢帧计数
        if (status.is_new_game or status.is_red_start or status.is_black_start or \
           status.is_my_step or status.is_opponent_step) and \
           not status.is_history_mismatch:
            if self.checker.consecutive_drops > 0:
                 logger.debug("重置丢帧计数 (原因: ValidStatus)")
            self.checker.consecutive_drops = 0
            self.checker._pending_lift_source = None

        # 3. 局面重复 (高频状态，优先检查)
        if status.is_same_board:
            return self._handle_same_board(state)

        # 4. 非法状态（非法局面或非法变化 或 历史不一致 或 多步变化）
             # 将所有异常状态统一视为"非法状态"（Drop Frame），复用统一的防抖重置机制
        if status.is_illegal_board or status.is_illegal_change or status.is_history_mismatch or status.is_multi_step:
            return self._handle_illegal_board(state)
        # 5. 我方走棋
        elif status.is_my_step:
            return self._handle_my_move(state)
        # 6. 对手走棋
        elif status.is_opponent_step:
            if self.context.capture_depth_enabled:
                captured_piece = status.step_info.get('captured_piece')
                if self.checker.record_own_piece_captured(captured_piece):
                    self._publish_capture_depth_update(captured_piece)
            return self._handle_opponent_move(state, callback)

        # 7. 新对局(注意: 新对局不是指初始局面)
        if status.is_new_game:
            self.checker.reset_capture_depth_bonus()
            self._publish_capture_depth_update()
            self._handle_new_game()
        # 8. 红方开局
        if status.is_red_start:
            self.checker.reset_capture_depth_bonus()
            self._publish_capture_depth_update()
            return self._handle_red_start(state, callback)            
        # 9. 黑方开局
        if status.is_black_start:
            self.checker.reset_capture_depth_bonus()
            self._publish_capture_depth_update()
            return self._handle_black_start(state)

        return BoardAnalysisState()

    def _publish_capture_depth_update(self, captured_piece=None):
        """通知UI刷新基础深度与本局动态加成。"""
        engine_params = self.context.get_engine_params()
        try:
            base_depth = int(engine_params.get('depth', 20))
        except (TypeError, ValueError):
            base_depth = 20
        bonus = self.checker.capture_depth_bonus
        message_bus.publish(Message(
            MessageType.PARAM_UPDATE,
            base_depth + bonus,
            base_depth=base_depth,
            depth_bonus=bonus,
            captured_piece=captured_piece,
        ))

    def _handle_red_start(self, state, callback):
        # 处理红方开局
        self.history.clear()
        self.context.base_fen = None # 清除锚点，回归startpos
        message_bus.publish(Message(
            MessageType.CHANGE,
            "红方开局",
            array=state.board_array,
            step_info=state.board_status.step_info
        ))

        return self._get_engine_move(
            '', None, state, callback
        )

    def _handle_black_start(self, state):
        # 处理黑方开局
        self.history.clear()
        self.context.base_fen = None # 清除锚点，回归startpos
        message_bus.publish(Message(
            MessageType.CHANGE,
            "黑方开局",
            array=state.board_array,
            step_info=state.board_status.step_info
        ))
        

        return BoardAnalysisState()

    def _handle_new_game(self):
        # 处理新对局
        self.history.clear()
        self.context.base_fen = None
        logger.debug("新对局或多步移动, 清空历史记录.")

    def _handle_same_board(self, state):
        # 处理局面重复
        if (
            getattr(self.context, 'game_variant', 'xiangqi') == "jieqi"
            and getattr(self.checker, 'pending_jieqi_analysis_retry', False)
        ):
            # 引擎着法与视觉棋盘不一致时会先清视觉缓存并重拍。重拍得到的
            # 往往正是同一可信局面；它不是“无事可做”，而是恢复分析的确认帧。
            self.checker.pending_jieqi_analysis_retry = False
            retry_count = getattr(self.checker, 'jieqi_analysis_retry_count', 1)
            moves = self.history.get_moves_str() if self.history else ""
            fen_str, _ = utils.convert_array_to_fen(
                state.board_array, self.checker.is_red
            )

            def callback(msg):
                message_bus.publish(msg)

            logger.info(
                f"揭棋视觉复核通过（局面未变化），自动恢复引擎分析，"
                f"retry={retry_count}"
            )
            message_bus.publish(Message(
                MessageType.STATUS,
                "局面复核完成，正在重新计算...",
            ))
            return self._get_engine_move(
                fen_str,
                moves,
                state,
                callback,
                is_newgame_override=True,
                desync_retry=retry_count,
            )
        return BoardAnalysisState()

    def _handle_illegal_board(self, state):
        status = state.board_status
        if status is not None:
            message = status.message

            # 棋子长时间悬空时画面只有“起点变空”，这不是完整走法。
            # 永远保留上一可信局面，不累计强制同步计数，也不额外排队重拍；
            # 连续截图会在棋子真正落下后自然得到完整的两个端点。
            if status.step_info.get('transient_single_change'):
                position = status.step_info.get('position')
                if self.checker._pending_lift_source != position:
                    logger.info(
                        f"暂存悬子/不完整走子: position={position}, "
                        f"piece={status.step_info.get('piece')}"
                    )
                self.checker._pending_lift_source = position
                self.checker.consecutive_drops = 0
                return BoardAnalysisState()

            logger.warning(f"转入非法状态处理，原因: {message}")
            
            # --- 强制同步逻辑 ---
            # 只要是连续非法，无论原因是什么，都进行计数
            self.checker.consecutive_drops += 1
            logger.debug(f"连续丢帧计数: {self.checker.consecutive_drops}")

            if self.checker.consecutive_drops > 2:
                if getattr(self.context, 'game_variant', 'xiangqi') == "jieqi":
                    # 揭棋不能像普通象棋一样从当前FEN强制同步：单帧不含
                    # 已揭示历史与被吃暗子的身份。保留最后一次可信状态，
                    # 清视觉缓存后重新识别，避免把历史永久清空。
                    logger.warning("揭棋连续异常：保留可信历史并执行视觉软刷新")
                    self.context.reset_recognizer()
                    self.checker.consecutive_drops = 0
                    self.context.discard_before_timestamp = time.time()
                    message_bus.publish(Message(
                        MessageType.RETRY_CAPTURE,
                        "揭棋识别异常，已保留历史并重新识别",
                    ))
                    return BoardAnalysisState()

                # 非法局面（棋子数量/位置非法）不能强制同步
                if status.is_illegal_board:
                    logger.debug(f"拒绝强制同步(非法局面)，继续重试。: {message}")
                    self.context.discard_before_timestamp = time.time()
                    message_bus.publish(Message(MessageType.RETRY_CAPTURE, message))
                    return BoardAnalysisState()
                
                # 非法移动可以强制同步
                logger.debug("触发强制同步(非法移动)! 强制接受当前局面.")
                self.checker.force_sync_board(state.board_array)
                self.checker.consecutive_drops = 0
                message = "触发强制同步，重置Checker状态"
                

                # 关键修复：强制同步后，立即发送变更消息更新UI
                # 否则下一帧会被判定为"相同局面"而被忽略，导致界面卡在这一帧
                message_bus.publish(Message(
                    MessageType.CHANGE,
                    "强制同步更新",
                    array=state.board_array,
                    step_info={} 
                ))

                # 关键修复2：重置后立即触发引擎分析
                # 因为丢失了历史，我们当作"残局/中局"处理
                # 使用当前FEN作为新的base_fen
                fen_str, _ = utils.convert_array_to_fen(state.board_array, self.checker.is_red)
                self.history.clear()
                self.context.base_fen = fen_str # 设置锚点
                
                # 定义回调方便Engine回传消息
                def callback(msg):
                    message_bus.publish(msg)

                logger.debug("强制同步后触发引擎分析...")
                
                # 智能判断：如果触发强制同步的是"我方走棋"（例如历史不一致），则不应触发引擎分析
                if status.is_my_step:
                    logger.debug("触发源为我方走棋，转为对方思考，跳过引擎分析")
                    message_bus.publish(Message(
                        MessageType.CHANGE,
                        MessageContent.OPPONENT_TURN,
                        array=state.board_array,
                        step_info=state.board_status.step_info
                    ))
                    return BoardAnalysisState()
                
                # 否则（对方走棋 或 无法判断的非法移动），默认触发引擎分析
                return self._get_engine_move(fen_str, "", state, callback, is_newgame_override=True)
            
            # --- 非强制同步的非法局面处理 ---
            self.context.discard_before_timestamp = time.time()  # 过滤旧帧
            message_bus.publish(Message(MessageType.RETRY_CAPTURE, message))
            logger.debug(f"非法局面: {message}")
        
        return BoardAnalysisState()



    def _handle_my_move(self, state):
        # 处理己方走棋
        self.checker.pending_jieqi_analysis_retry = False
        self.checker.jieqi_analysis_retry_count = 0
        
        # print("Debug - 我方走棋")

        message_bus.publish(Message(
            MessageType.CHANGE,
            MessageContent.OPPONENT_TURN,
            array=state.board_array,
            step_info=state.board_status.step_info
        ))
        
        # 记录我方走棋历史
        move_str = utils.convert_coords_to_move(
            state.board_status.step_info.get('from_pos'),
            state.board_status.step_info.get('to_pos'),
            self.checker.is_red
        )
        move_str = self._encode_variant_move(move_str, state.board_status.step_info)
        # print(f"Debug - 我方走棋记录: {move_str}")
        
        # 更新历史记录
        all_moves = self.history.add_and_get_all("", move_str, "", self.checker.is_red)
        # print(f"Debug - 我方走棋后完整历史记录: {all_moves}")
        
        return BoardAnalysisState()

    def _handle_opponent_move(self, state, callback):
        # 处理对方走棋
        self.checker.pending_jieqi_analysis_retry = False
        self.checker.jieqi_analysis_retry_count = 0
        message_bus.publish(Message(
            MessageType.CHANGE,
            MessageContent.MY_TURN,
            array=state.board_array,
            step_info=state.board_status.step_info
        ))

        fen_str, board = utils.convert_array_to_fen(state.board_array, self.checker.is_red)
        move_str = utils.convert_coords_to_move(
            state.board_status.step_info.get('from_pos'),
            state.board_status.step_info.get('to_pos'),
            self.checker.is_red
        )
        move_str = self._encode_variant_move(move_str, state.board_status.step_info)
        
        # 更新历史记录
        all_moves = self.history.add_and_get_all("", move_str, "", self.checker.is_red)
        moves_count = len(all_moves.split()) if all_moves else 0
        
        # 获取引擎着法
        logger.debug("开始引擎分析...")
        return self._get_engine_move(
            fen_str, all_moves, state, callback
        )

    def _encode_variant_move(self, move_str, step_info):
        """给揭棋暗子着法附加揭示身份，供PikaJieQi正确回放历史。"""
        if getattr(self.context, 'game_variant', 'xiangqi') != "jieqi" or not move_str:
            return move_str
        if step_info.get('piece') not in ('X', 'x'):
            return move_str
        revealed = step_info.get('revealed_piece')
        if revealed and revealed not in ('-', 'X', 'x'):
            return move_str + revealed
        logger.warning("揭棋暗子已移动，但未识别到揭示后的棋种: %s", step_info)
        return move_str

    def _get_engine_move(
        self, fen_str, moves, state, callback, is_newgame_override=False,
        desync_retry=0, engine_retry=0, search_override=None,
    ) -> BoardAnalysisState:
        # 获取引擎着法 (异步多线程版)
        analysis_token = self.context.next_analysis_token()

        # 后台分析必须使用不可变快照，避免后续识别帧覆盖转换所用棋盘。
        analysis_board = (
            [row[:] for row in state.board_array]
            if state.board_array else None
        )
        
        # 2. 保存当前状态供"变招"使用
        self.checker.last_fen_str = fen_str
        self.checker.last_board_array_for_engine = (
            [row[:] for row in analysis_board]
            if analysis_board else None
        )
        
        # 3. 准备参数
        # [Engine Correction] 
        # 必须严格区分"当前画面FEN"(用于验证)和"引擎起始FEN"(用于计算)
        # 如果提供了历史 moves，引擎必须从 Anchor (Startpos 或 BaseFEN) 开始计算，绝对不能从当前FEN开始加Moves
        verify_fen = fen_str if fen_str else (self.context.base_fen if self.context.base_fen else "startpos")
        
        engine_fen = None
        use_startpos = False
        
        if moves:
            # 模式A: 连续模式 (有历史) -> 忽略传入的当前FEN，强制从Anchor开始
            engine_fen = self.context.base_fen
            use_startpos = (engine_fen is None)
        else:
            # 模式B: 静态模式 (无历史/强制重置) -> 使用传入的当前FEN作为起点
            engine_fen = fen_str if fen_str else self.context.base_fen
            use_startpos = (engine_fen is None)

        # 局面不连续时（强制同步、历史重置等），必须发送 newgame 命令
        is_newgame = is_newgame_override or state.board_status.is_new_game
        is_red = self.checker.is_red
        depth_bonus = (
            self.checker.capture_depth_bonus
            if self.context.capture_depth_enabled else 0
        )
        
        # [DEBUG] 追踪关键状态
        logger.debug(f"Analysis Context: IsNewGame={is_newgame}, IsRed={is_red}")
        logger.debug(f"  EngineFEN: {engine_fen if engine_fen else 'startpos'}")
        logger.debug(f"  VerifyFEN: {verify_fen}")
        logger.debug(f"  Moves: {moves}")
        logger.debug(f"  CaptureDepthBonus: {depth_bonus}")
        
        # 4. 定义后台任务
        def run_analysis():
            try:
                # [Watchdog] 启动看门狗定时器，防止引擎计算超时卡死
                # 固定深度加深时同步延长安全上限，最高允许5分钟。
                watchdog_timeout = self.engine.get_search_timeout(
                    depth_bonus, search_override
                )
                watchdog_timer = threading.Timer(watchdog_timeout, self.engine.stop_analysis)
                watchdog_timer.start()
                
                try:
                    # 执行阻塞式分析
                    move, fen, pvs = self.engine.get_bestmove(
                        engine_fen,
                        is_red,
                        callback, 
                        use_startpos=use_startpos,
                        is_newgame=is_newgame, 
                        moves=moves,
                        multipv=1,
                        depth_bonus=depth_bonus,
                        search_override=search_override,
                    )
                finally:
                    # 无论成功或异常，必须取消定时器
                    watchdog_timer.cancel()
                
                # 存储备选着法
                if not self.context.is_analysis_token_current(analysis_token):
                    logger.debug(f"忽略过期引擎结果: token={analysis_token}, move={move}")
                    return

                self.checker.last_pvs = pvs

                # 固定深度搜索可能在看门狗stop后没有来得及输出bestmove，
                # 但此前的info pv仍是完整合法候选。优先复用最后PV首步，
                # 避免把已经计算数十秒的结果全部丢弃。
                move = self._best_available_engine_move(move, pvs)
                
                # 检查着法有效性
                if not move or len(move) != 4:
                    logger.warning(f"Engine returned invalid move: '{move}', fen={verify_fen}, moves={moves}")
                    self._recover_from_empty_engine_move(
                        fen_str=fen_str,
                        moves=moves,
                        state=state,
                        callback=callback,
                        engine_retry=engine_retry,
                    )
                    return
                
                # 转换并推送结果
                chinese_move = utils.convert_move_to_chinese(move, analysis_board, is_red)
                
                # 引擎局面与视觉局面漂移时，自动以当前FEN重新锚定并重算。
                if chinese_move is None:
                    logger.warning(f"着法转换失败(无效/非法): {move} on board_fen={verify_fen}")
                    self._recover_from_engine_desync(
                        move=move,
                        state=state,
                        analysis_board=analysis_board,
                        callback=callback,
                        desync_retry=desync_retry,
                    )
                    return
                
                logger.debug(f"Engine Analysis Done: {move}")
                self.checker.consecutive_mismatches = 0
                self.checker.pending_jieqi_analysis_retry = False
                self.checker.jieqi_analysis_retry_count = 0
                
                # 检查是否已在结算画面
                if self.checker.in_settlement_screen:
                    logger.info(f"检测到结算画面，忽略着法推送: {move}")
                    return

                message_bus.publish(Message(MessageType.MOVE_TEXT, chinese_move))
                message_bus.publish(Message(
                    MessageType.MOVE_CODE,
                    move,
                    is_red=is_red,
                    analysis_token=analysis_token,
                    auto_execute=True,
                ))
                message_bus.publish(Message(MessageType.STATUS, "推荐走法："))
                
            except Exception as e:
                logger.error(f"引擎分析失败: {str(e)}")
                message_bus.publish(Message(MessageType.ERROR, f"引擎分析失败: {str(e)}"))
        
        # 5. 启动后台线程
        analysis_thread = threading.Thread(target=run_analysis, daemon=True)
        analysis_thread.start()
        
        return BoardAnalysisState()

    @staticmethod
    def _best_available_engine_move(move, pvs):
        """bestmove缺失时安全采用最后PV的首步。"""
        if move and isinstance(move, str) and len(move) == 4:
            return move
        for candidate in pvs or []:
            if not isinstance(candidate, str):
                continue
            candidate = candidate.split()[0][:4] if candidate.split() else ""
            if (
                len(candidate) == 4
                and candidate[0].isalpha()
                and candidate[2].isalpha()
                and candidate[1].isdigit()
                and candidate[3].isdigit()
            ):
                logger.warning(f"bestmove缺失，采用最后PV候选: {candidate}")
                return candidate
        return None

    def _recover_from_empty_engine_move(
        self, *, fen_str, moves, state, callback, engine_retry
    ):
        """无bestmove且无PV时自动快速重算，必要时重启引擎。"""
        if engine_retry == 0:
            message_bus.publish(Message(
                MessageType.STATUS,
                "引擎未及时返回着法，正在快速重算...",
            ))
            self._get_engine_move(
                fen_str,
                moves,
                state,
                callback,
                is_newgame_override=True,
                engine_retry=1,
                search_override=("movetime", "5000"),
            )
            return

        if engine_retry == 1:
            message_bus.publish(Message(
                MessageType.STATUS,
                "引擎响应异常，正在自动重启并重算...",
            ))
            try:
                self.engine.quit(fast=True)
                if not self.engine.start():
                    raise RuntimeError("Pikafish重新启动失败")
            except Exception as exc:
                logger.error(f"自动重启引擎失败: {exc}")
                message_bus.publish(Message(
                    MessageType.ERROR,
                    f"引擎自动重启失败: {exc}",
                ))
                return
            self._get_engine_move(
                fen_str,
                moves,
                state,
                callback,
                is_newgame_override=True,
                engine_retry=2,
                search_override=("movetime", "5000"),
            )
            return

        message_bus.publish(Message(
            MessageType.ERROR,
            "引擎重启后仍未返回着法，请检查引擎文件",
        ))

    def _recover_from_engine_desync(
        self,
        *,
        move,
        state,
        analysis_board,
        callback,
        desync_retry,
    ):
        """恢复引擎历史与视觉棋盘不一致，避免相同局面永久卡住。"""
        if not analysis_board:
            message_bus.publish(Message(
                MessageType.ERROR,
                "引擎局面不同步且缺少棋盘快照，正在自动刷新",
            ))
            self.context.discard_before_timestamp = time.time()
            message_bus.publish(Message(MessageType.RETRY_CAPTURE, "引擎局面不同步"))
            return

        if getattr(self.context, 'game_variant', 'xiangqi') == "jieqi":
            # 当前画面的普通FEN无法表达暗子池和揭示历史，不能像普通象棋
            # 那样用它重新锚定引擎。保留历史，等待一张新的稳定帧复核。
            logger.warning(
                f"揭棋着法与视觉不一致，保留历史并软刷新: invalid_move={move}"
            )
            if desync_retry >= 1:
                # 已在新稳定帧上重算过一次仍不一致，继续循环重拍只会反复
                # 消耗CPU。明确报错并等待下一次真实棋盘变化或用户刷新。
                self.checker.pending_jieqi_analysis_retry = False
                self.checker.jieqi_analysis_retry_count = 0
                message_bus.publish(Message(
                    MessageType.ERROR,
                    "揭棋历史与引擎局面仍不一致，请点击刷新后继续",
                ))
                return

            self.checker.pending_jieqi_analysis_retry = True
            self.checker.jieqi_analysis_retry_count = desync_retry + 1
            self.context.invalidate_analysis()
            self.engine.stop_analysis()
            self.context.reset_recognizer()
            self.context.discard_before_timestamp = time.time()
            message_bus.publish(Message(
                MessageType.STATUS,
                "揭棋画面识别不稳定，已保留走子历史并重新识别...",
            ))
            message_bus.publish(Message(
                MessageType.RETRY_CAPTURE,
                "揭棋着法视觉复核",
            ))
            return

        current_fen, _ = utils.convert_array_to_fen(
            analysis_board,
            self.checker.is_red,
        )
        if desync_retry < 1:
            logger.warning(
                f"自动重同步引擎局面: invalid_move={move}, anchor={current_fen}"
            )
            self.history.clear()
            self.context.base_fen = current_fen
            self.checker.force_sync_board(analysis_board)
            message_bus.publish(Message(
                MessageType.STATUS,
                "检测到引擎局面漂移，正在自动重新同步...",
            ))
            self._get_engine_move(
                current_fen,
                "",
                state,
                callback,
                is_newgame_override=True,
                desync_retry=desync_retry + 1,
            )
            return

        # 当前FEN重算仍失败：执行与手动刷新等价的硬恢复，再由重试截图
        # 流程重新建立棋盘与历史。保留本局动态深度加成。
        logger.error(
            f"当前FEN重算仍返回非法着法: {move}; 执行自动硬刷新"
        )
        preserved_depth_bonus = self.checker.capture_depth_bonus
        self.context.invalidate_analysis()
        self.engine.stop_analysis()
        self.history.clear()
        self.context.base_fen = None
        self.context.reset_checker()
        self.checker.capture_depth_bonus = preserved_depth_bonus
        self.context.reset_recognizer()
        self.context.discard_before_timestamp = time.time()
        message_bus.publish(Message(
            MessageType.ERROR,
            "引擎局面同步失败，已自动刷新并重新识别",
        ))
        message_bus.publish(Message(
            MessageType.RETRY_CAPTURE,
            "引擎局面同步失败，自动硬刷新",
        ))

    def request_alternative_move(self):
        """
        请求变招（获取第二好的着法）。
        必须在有最近的一步棋分析后调用。
        """
        if not hasattr(self.checker, 'last_fen_str') or not self.checker.last_fen_str:
             logger.error("无法变招：没有最近的棋盘状态")
             return

        logger.debug("用户请求变招 (MultiPV=2)...")
        
        try:
             # 复用上次的 history 和 FEN
             # MoveHistory 没有 get_all_moves 方法，需要手动提取
             move_records = self.history.all_moves()
             all_moves = " ".join([r.move for r in move_records if r.move])
             fen_str = self.checker.last_fen_str
             
             # 调用引擎获取前2名
             best_move, fen, pvs = self.engine.get_bestmove(
                fen_str, 
                self.checker.is_red, 
                None, 
                use_startpos=(self.context.base_fen is None), 
                moves=all_moves,
                multipv=2,
                depth_bonus=(
                    self.checker.capture_depth_bonus
                    if self.context.capture_depth_enabled else 0
                ),
             )
             
             # 获取第二好的着法
             alt_move = None
             # pvs 是按 rank 排序的 list
             # pvs[0] 是最佳, pvs[1] 是次佳
             if len(pvs) >= 2:
                 alt_move = pvs[1]  # get_bestmove 返回的是 move 字符串列表
             elif len(pvs) == 1:
                 # 只有一招？那也没办法变
                 logger.warning("只有唯一着法，无法变招")
                 return
             
             if alt_move:
                 logger.debug(f"变招成功: {alt_move}")
                 # 转换并推送
                 chinese_move = utils.convert_move_to_chinese(alt_move, self.checker.last_board_array_for_engine, self.checker.is_red)
                 
                 # 如果着法无效，跳过推送
                 if chinese_move is None:
                     return
                 
                 # 加上 "(变)" 前缀以示区别
                 message_bus.publish(Message(MessageType.MOVE_TEXT, f"🥈 {chinese_move}"))
                 message_bus.publish(Message(MessageType.MOVE_CODE, alt_move, is_red=self.checker.is_red))
             else:
                 logger.debug("未找到变招")

        except Exception as e:
            logger.error(f"变招失败: {e}")


def start_process_worker(process_queue, result_queue, stop_event=None):
    result_dict = {}
    result_lock = threading.Lock()
    result_ready = threading.Condition(result_lock)
    NUM_WORKERS = 2

    def process_worker():
        # 处理棋盘截图,转为局面数组, 并检查局面状态
        while True:
            if stop_event and stop_event.is_set():
                break
            item = process_queue.get()  # 阻塞等待任务
            if item == "STOP":
                break
            capture_time, screenshot = item
            
            # 过滤在 RETRY 之前截图的帧
            if capture_time < context.discard_before_timestamp:
                logger.debug(f"丢弃过期帧 (截图时间 {capture_time:.3f} < RETRY时间 {context.discard_before_timestamp:.3f})")
                process_queue.task_done()
                continue
            
            result = ChessProcess.from_context(context)._process_image(screenshot, capture_time)
            with result_lock:
                result_dict[capture_time] = result
                result_ready.notify_all()
            process_queue.task_done()

    def result_sort_worker():
        # 按时间戳给结果排序
        while True:
            if stop_event and stop_event.is_set():
                break
            with result_lock:
                if not result_dict:
                    # 使用短超时检查stop_event，避免关闭程序时永久睡在条件
                    # 变量上，迫使UI逐线程等待完整join超时。
                    result_ready.wait(timeout=0.2)
                    if stop_event and stop_event.is_set():
                        return
                    if not result_dict:
                        continue
                # 按时间戳排序，最早的最先处理
                earliest_time = min(result_dict.keys())
                process_result = result_dict.pop(earliest_time)
                result_queue.put(process_result)

    def result_handler_worker():
        # 对不同局面状态分发处理
        last_result_time = time.time()
        last_valid_activity_time = time.time() # [Auto-Stop] 最后一次有效活动时间
        
        while True:
            if stop_event and stop_event.is_set():
                break
            try:
                # 使用超时获取结果，避免无限等待
                process_result = result_queue.get(timeout=1.0)
                if process_result == "STOP":
                    break
                
                if process_result:
                    # 1. 处理状态分发
                    if process_result.board_status is not None or process_result.is_settlement_screen:
                        proc = ChessProcess.from_context(context)
                        proc._handle_status(process_result)
                    
                    # 2. [Auto-Stop] 更新有效活动时间
                    # 只要不是结算画面，且 BoardStatus 存在且为 Active 状态，就视为"活跃"
                    if not process_result.is_settlement_screen and \
                       process_result.board_status is not None and \
                       process_result.board_status.is_active:
                        last_valid_activity_time = time.time()
                
                result_queue.task_done()
                last_result_time = time.time()  # 更新最后获取结果的时间
            except queue.Empty:
                # 检查是否超过30秒没有获取到结果 (Keep Alive)
                current_time = time.time()
                if current_time - last_result_time > 30.0:
                    message_bus.publish(Message(MessageType.RETRY_CAPTURE, "Keep-Alive"))
                    last_result_time = current_time  # 重置 Keep Alive 计时器

                # [Smart Auto-Stop] 智能自动停止
                # 如果连续 180秒 没有处理过任何"正常有效"的局面 (Valid Activity)，则停止
                if current_time - last_valid_activity_time > 180.0:
                    logger.info("智能自动停止触发: 超过180秒无有效对局活动") 
                    # 直接 break 退出循环，停止线程
                    message_bus.publish(Message(MessageType.STOP))
                    break

            except Exception as e:
                logger.error(f"结果处理线程出错: {e}")

    threads = []
    for _ in range(NUM_WORKERS): 
        t = threading.Thread(target=process_worker, daemon=True) # 2个线程,负责识别与检查
        t.start()
        threads.append(t)
    t = threading.Thread(target=result_sort_worker, daemon=True) # 1个线程,负责排序
    t.start()
    threads.append(t)
    t = threading.Thread(target=result_handler_worker, daemon=True) # 1个线程,负责处理结果
    t.start()
    threads.append(t)

    return threads
