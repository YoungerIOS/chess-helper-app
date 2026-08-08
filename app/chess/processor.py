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
            return self._handle_opponent_move(state, callback)

        # 7. 新对局(注意: 新对局不是指初始局面)
        if status.is_new_game:
            self._handle_new_game()
        # 8. 红方开局
        if status.is_red_start:
            return self._handle_red_start(state, callback)            
        # 9. 黑方开局
        if status.is_black_start:
            return self._handle_black_start(state)

        return BoardAnalysisState()

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
        return BoardAnalysisState()

    def _handle_illegal_board(self, state):
        status = state.board_status
        if status is not None:
            message = status.message
            logger.warning(f"转入非法状态处理，原因: {message}")
            
            # --- 强制同步逻辑 ---
            # 只要是连续非法，无论原因是什么，都进行计数
            self.checker.consecutive_drops += 1
            logger.debug(f"连续丢帧计数: {self.checker.consecutive_drops}")

            if self.checker.consecutive_drops > 2:
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
        # print(f"Debug - 我方走棋记录: {move_str}")
        
        # 更新历史记录
        all_moves = self.history.add_and_get_all("", move_str, "", self.checker.is_red)
        # print(f"Debug - 我方走棋后完整历史记录: {all_moves}")
        
        return BoardAnalysisState()

    def _handle_opponent_move(self, state, callback):
        # 处理对方走棋
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
        
        # 更新历史记录
        all_moves = self.history.add_and_get_all("", move_str, "", self.checker.is_red)
        moves_count = len(all_moves.split()) if all_moves else 0
        
        # 获取引擎着法
        logger.debug("开始引擎分析...")
        return self._get_engine_move(
            fen_str, all_moves, state, callback
        )

    def _get_engine_move(self, fen_str, moves, state, callback, is_newgame_override=False) -> BoardAnalysisState:
        # 获取引擎着法 (异步多线程版)
        
        # 2. 保存当前状态供"变招"使用
        self.checker.last_fen_str = fen_str
        self.checker.last_board_array_for_engine = state.board_array
        
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
        
        # [DEBUG] 追踪关键状态
        logger.debug(f"Analysis Context: IsNewGame={is_newgame}, IsRed={is_red}")
        logger.debug(f"  EngineFEN: {engine_fen if engine_fen else 'startpos'}")
        logger.debug(f"  VerifyFEN: {verify_fen}")
        logger.debug(f"  Moves: {moves}")
        
        # 4. 定义后台任务
        def run_analysis():
            try:
                # [Watchdog] 启动看门狗定时器，防止引擎计算超时卡死
                # 设定30秒超时（比引擎内部35秒超时提前5秒panic）
                watchdog_timer = threading.Timer(30.0, self.engine.stop_analysis)
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
                        multipv=1 
                    )
                finally:
                    # 无论成功或异常，必须取消定时器
                    watchdog_timer.cancel()
                
                # 存储备选着法
                self.checker.last_pvs = pvs
                
                # 检查着法有效性
                if not move or len(move) != 4:
                    logger.warning(f"Engine returned invalid move: '{move}', fen={verify_fen}, moves={moves}")
                    message_bus.publish(Message(MessageType.ERROR, f"引擎未返回有效着法"))
                    return
                
                # 转换并推送结果
                chinese_move = utils.convert_move_to_chinese(move, self.checker.last_board_array_for_engine, is_red)
                
                # 如果着法无效（起点无棋子或是对方棋子），跳过推送
                if chinese_move is None:
                    logger.warning(f"着法转换失败(无效/非法): {move} on board_fen={verify_fen}")
                    return
                
                logger.debug(f"Engine Analysis Done: {move}")
                
                # 检查是否已在结算画面
                if self.checker.in_settlement_screen:
                    logger.info(f"检测到结算画面，忽略着法推送: {move}")
                    return

                message_bus.publish(Message(MessageType.MOVE_TEXT, chinese_move))
                message_bus.publish(Message(MessageType.MOVE_CODE, move, is_red=is_red))
                message_bus.publish(Message(MessageType.STATUS, "推荐走法："))
                
            except Exception as e:
                logger.error(f"引擎分析失败: {str(e)}")
                message_bus.publish(Message(MessageType.ERROR, f"引擎分析失败: {str(e)}"))
        
        # 5. 启动后台线程
        analysis_thread = threading.Thread(target=run_analysis, daemon=True)
        analysis_thread.start()
        
        return BoardAnalysisState()

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
                multipv=2
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
                    result_ready.wait()
                    if stop_event and stop_event.is_set():
                        return
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
