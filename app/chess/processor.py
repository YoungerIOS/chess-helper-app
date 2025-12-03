from app.chess.recognizer import ChessRecognizer
from app.chess.message import Message, MessageType, MessageContent, TurnState
from app.chess.message_bus import message_bus
from app.chess.context import context
from app.chess.checker import BoardStatus
from app.tools import utils
from pprint import pformat
from typing import Tuple, Optional, Dict, Any, List
from dataclasses import dataclass
import threading, queue, time


@dataclass
class ProcessResult:
    board_array: Optional[list] = None
    board_status: Optional[BoardStatus] = None

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
        self.recognizer = ChessRecognizer(self.context)
    

    def _process_image(self, img):
        """主流程入口，处理图像并返回相应消息"""
        # 1. 识别棋盘和棋子
        board = self._recognize_pieces(img)
        if board is None:
            return ProcessResult()

        # 2. 检查局面状态
        with context._checker_lock:
            status = self.checker.check_board(board)
        # print("Debug - 局面检查:\n" + pformat(status))
        
        return ProcessResult(board_array=board, board_status=status)
    
    def _handle_status(self, turn, board_array, status):
        def callback(msg):
            message_bus.publish(msg)
        # print(f"Debug - 当前轮次: {turn}")
        # 初始局
        self.use_startpos = True
        # 3. 根据不同状态分发处理
        # 新对局(注意: 新对局不是指初始局面)
        if status.is_new_game:
            self._handle_new_game()
        # 红方开局
        if status.is_red_start:
            return self._handle_red_start(board_array, status, callback)            
        # 黑方开局
        if status.is_black_start:
            return self._handle_black_start(board_array, status)
        # 局面重复
        if status.is_same_board:
            return self._handle_same_board()
        # 局面不合法
        if status.is_illegal:
            return self._handle_illegal_board(status)
        # 己方走棋
        if status.is_my_step:
            return self._handle_my_move(board_array, status)
        # 对方走棋
        if status.is_opponent_step:
            return self._handle_opponent_move(board_array, status, callback)
        # 多步移动
        if status.is_multi_step:
            return self._handle_multi_step(turn, board_array, status, callback)

        return ProcessResult()
        
    def _recognize_pieces(self, img) -> Optional[list]:
        # 识别棋盘和棋子
        platform = self.context.get_platform(self.context.platform)
        coords = getattr(platform, 'board_coords', {}) or {}
        x_array = coords.get("x", [])
        y_array = coords.get("y", [])

        try:
            board_array = self.recognizer.recognize_piece_from_grid(img, x_array, y_array)
        except self.recognizer.RecognitionError as e:
            print(f"棋子识别失败: {e}")
            message_bus.publish(Message(MessageType.RETRY_CAPTURE, f"{e}"))
            return None
        except Exception as e:
            print(f"棋子识别发生未知错误: {e}")
            return None

        return board_array

    def _handle_red_start(self, board_array, result, callback):
        # 处理红方开局
        self.use_startpos = True
        self.history.clear()
        message_bus.publish(Message(
            MessageType.CHANGE,
            "红方开局",
            array=board_array,
            step_info=result.step_info
        ))
            
        return self._get_engine_move(
            '', None, board_array, result, callback
        )

    def _handle_black_start(self, board_array, result):
        # 处理黑方开局
        self.use_startpos = True
        self.history.clear()
        message_bus.publish(Message(
            MessageType.CHANGE,
            "黑方开局",
            array=board_array,
            step_info=result.step_info
        ))
        return ProcessResult()

    def _handle_new_game(self):
        # 处理新对局
        self.history.clear()
        print("Debug - 新对局或多步移动, 清空历史记录.")

    def _handle_same_board(self):
        # 处理局面重复
        # print("Debug - 重复画面, 继续处理下一张.")
        return ProcessResult()

    def _handle_illegal_board(self, status):
        # 将/帅数量错误时先去重新定位棋盘
        if status is not None:
            message = status.message
            message_bus.publish(Message(MessageType.RETRY_CAPTURE, message))
            print(f"Debug - 非法局面: {message}")
        
        return ProcessResult()

    def _handle_my_move(self, board_array, result):
        # 处理己方走棋
        message_bus.publish(Message(
            MessageType.CHANGE,
            MessageContent.OPPONENT_TURN,
            array=board_array,
            step_info=result.step_info
        ))
        
        # 记录我方走棋历史
        move_str = utils.convert_coords_to_move(
            result.step_info.get('from_pos'),
            result.step_info.get('to_pos'),
            self.checker.is_red
        )
        # print(f"Debug - 我方走棋记录: {move_str}")
        
        # 更新历史记录
        all_moves = self.history.add_and_get_all("", move_str, "", self.checker.is_red)
        # print(f"Debug - 我方走棋后完整历史记录: {all_moves}")
        
        return ProcessResult()

    def _handle_opponent_move(self, board_array, result, callback):
        # 处理对方走棋
        message_bus.publish(Message(
            MessageType.CHANGE,
            MessageContent.MY_TURN,
            array=board_array,
            step_info=result.step_info
        ))

        fen_str, board = utils.convert_array_to_fen(board_array, self.checker.is_red)
        move_str = utils.convert_coords_to_move(
            result.step_info.get('from_pos'),
            result.step_info.get('to_pos'),
            self.checker.is_red
        )
        # print(f"Debug - 对方走棋记录: {move_str}")
        
        # 更新历史记录
        all_moves = self.history.add_and_get_all("", move_str, "", self.checker.is_red)
        moves_count = len(all_moves.split()) if all_moves else 0
        # 开局15步后，用fen
        self.use_startpos = moves_count < 15
        # 校验历史
        if self.use_startpos:
            correct_fen = self.engine.verify_history(all_moves)
            if correct_fen and correct_fen != fen_str:
                print(f"Debug - 历史记录复盘结果不一致: {correct_fen} != {fen_str}")
                self.history.clear()
                self.use_startpos = False
        
        # print(f"Debug - 完整历史记录-----: {all_moves}")

        # 获取引擎着法
        print("Debug - 开始引擎分析...")
        return self._get_engine_move(
            fen_str, all_moves, board, result, callback
        )

    def _handle_multi_step(self, turn, board_array, result, callback):
        # 更新棋子位置
        message_bus.publish(Message(
            MessageType.PIECES,
            "更新棋子位置",
            array=board_array
        ))

        # 处理多步变化
        self.history.clear()
        self.use_startpos = False
        fen_str, board = utils.convert_array_to_fen(board_array, self.checker.is_red)
           
        # 获取引擎着法
        if turn is not None and turn == TurnState.OUR_SIDE:
            print("Debug - 多步移动, 己方走棋.")
            return self._get_engine_move(
                fen_str, None, board, result, callback
            )
        else:
            return ProcessResult()

    def _get_engine_move(self, fen_str, moves, board_array, check_result, callback) -> ProcessResult:
        # 获取引擎着法
        try:
            move, fen = self.engine.get_bestmove(
                fen_str,
                self.checker.is_red,
                callback,
                use_startpos=self.use_startpos,
                is_newgame=check_result.is_new_game, 
                moves=moves
            )
            # print(f"Debug - 引擎分析结果: move={move}, FEN={fen}")
            
            chinese_move = utils.convert_move_to_chinese(move, board_array, self.checker.is_red)
            # 新增：推送到UI队列
            message_bus.publish(Message(MessageType.MOVE_TEXT, chinese_move))
            message_bus.publish(Message(MessageType.MOVE_CODE, move, is_red=self.checker.is_red))
                
            return ProcessResult()
            
        except Exception as e:
            print(f"引擎分析失败: {str(e)}")
            message_bus.publish(Message(MessageType.ERROR, f"引擎分析失败: {str(e)}"))
            # 注意：这里不应该发送CHANGE消息，因为没有array字段
                
            return ProcessResult()

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
            capture_time, current_turn, screenshot = item
            result = ChessProcess.from_context(context)._process_image(screenshot)
            with result_lock:
                result_dict[capture_time] = (current_turn, result)
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
                current_turn, process_result = result_dict.pop(earliest_time)
                result_queue.put((current_turn, process_result))

    def result_handler_worker():
        # 对不同局面状态分发处理
        last_result_time = time.time()
        
        while True:
            if stop_event and stop_event.is_set():
                break
            try:
                # 使用超时获取结果，避免无限等待
                item = result_queue.get(timeout=1.0)
                if item == "STOP":
                    break
                current_turn, process_result = item
                if process_result and process_result.board_status is not None:
                    proc = ChessProcess.from_context(context)
                    proc._handle_status(
                        current_turn,
                        process_result.board_array,
                        process_result.board_status
                    )
                result_queue.task_done()
                last_result_time = time.time()  # 更新最后获取结果的时间
            except queue.Empty:
                # 检查是否超过5秒没有获取到结果
                if time.time() - last_result_time > 10.0:
                    # print("Debug - 10秒内未获取到处理结果，发送重试消息")
                    message_bus.publish(Message(MessageType.RETRY_CAPTURE, "空闲超过10秒, 防御性截图一次"))
                    last_result_time = time.time()  # 重置计时器
            except Exception as e:
                print(f"结果处理线程出错: {e}")

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

