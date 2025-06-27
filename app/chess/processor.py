from chess import recognizer
from tools.utils import convert_array_to_fen, convert_move_to_chinese, convert_coords_to_move
from chess.message import Message, MessageType
from chess.context import context
import time
from pprint import pformat
from typing import Tuple, Optional, Dict, Any, List
from dataclasses import dataclass

@dataclass
class MoveResult:
    move_text: Optional[Message] = None
    move_code: Optional[Message] = None

class ChessProcess:
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

    def process_image(self, img_origin, callback=None) -> MoveResult:
        """主流程入口，处理图像并返回相应消息"""
        # 1. 识别棋盘和棋子
        piece_array = self._recognize_board_and_pieces(img_origin, callback)
        if piece_array is None:
            return MoveResult()

        # 2. 检查局面状态
        result = self._check_board_status(piece_array)
        
        # 初始局
        self.use_startpos = True
        # 3. 根据不同状态分发处理
        # 新对局
        if result.is_new_game:
            self._handle_new_game()
        # 红方开局
        if result.is_red_start:
            return self._handle_red_start(piece_array, result, callback)
        # 黑方开局
        if result.is_black_start:
            return self._handle_black_start(piece_array, result, callback)
        # 局面重复或不合法
        if result.is_same_board or result.is_illegal:
            return self._handle_invalid_board()
        # 己方走棋
        if result.is_my_step:
            return self._handle_my_move(piece_array, result, callback)
        # 对方走棋
        if result.is_opponent_step:
            return self._handle_opponent_move(piece_array, result, callback)
        # 多步移动
        if result.is_multi_step:
            return self._handle_multi_step(piece_array, result, callback)

        return MoveResult()

    def _recognize_board_and_pieces(self, img_origin, callback) -> Optional[list]:
        # 识别棋盘和棋子
        try:
            x_array, y_array = recognizer.recognize_board(img_origin)
        except Exception as e:
            print(f"棋盘识别失败: {str(e)}")
            return None

        try:
            pieces_array = recognizer.recognize_piece_from_grid(
                img_origin, x_array, y_array, callback
            )
        except Exception as e:
            print(f"棋子识别失败: {str(e)}")
            return None

        if pieces_array is None:
            time.sleep(0.2)
            print("Debug - 动画遮挡或识别失败,延时0.2秒后继续截图循环")
            return None

        return pieces_array

    def _check_board_status(self, pieces_array):
        # 检查棋盘状态
        result = self.checker.check_board(pieces_array)
        print("Debug - 局面检查:\n" + pformat(result))
        return result

    def _handle_red_start(self, pieces_array, result, callback):
        # 处理红方开局
        self.use_startpos = True
        self.history.clear()
        if callback:
            callback(Message(
                MessageType.CHANGE,
                "红方开局",
                array=pieces_array,
                step_info=result.step_info
            ))
        return self._get_engine_move(
            '', None, pieces_array, result, callback
        )

    def _handle_black_start(self, pieces_array, result, callback):
        # 处理黑方开局
        self.use_startpos = True
        self.history.clear()
        if callback:
            callback(Message(
                MessageType.CHANGE,
                "黑方开局",
                array=pieces_array,
                step_info=result.step_info
            ))
        return MoveResult()

    def _handle_new_game(self):
        # 处理新对局
        self.history.clear()
        print("Debug - 新对局或多步移动, 清空历史记录.")

    def _handle_invalid_board(self):
        # 处理无效棋盘
        print("Debug - 局面重复或不合法, 继续截图循环.")
        return MoveResult()

    def _handle_my_move(self, pieces_array, result, callback):
        # 处理己方走棋
        if callback:
            callback(Message(
                MessageType.CHANGE,
                "我方已走棋",
                array=pieces_array,
                step_info=result.step_info
            ))
        
        # 记录我方走棋历史
        move_str = convert_coords_to_move(
            result.step_info.get('from_pos'),
            result.step_info.get('to_pos'),
            self.checker.is_red
        )
        print(f"Debug - 我方走棋记录: {move_str}")
        
        # 更新历史记录
        all_moves = self.history.add_and_get_all("", move_str, "", self.checker.is_red)
        print(f"Debug - 我方走棋后完整历史记录: {all_moves}")
        
        return MoveResult()

    def _handle_opponent_move(self, pieces_array, result, callback):
        # 处理对方走棋
        if callback:
            callback(Message(
                MessageType.CHANGE,
                "对方已走棋",
                array=pieces_array,
                step_info=result.step_info
            ))

        fen_str, board_array = convert_array_to_fen(pieces_array, self.checker.is_red)
        move_str = convert_coords_to_move(
            result.step_info.get('from_pos'),
            result.step_info.get('to_pos'),
            self.checker.is_red
        )
        print(f"Debug - 对方走棋记录: {move_str}")
        
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
        
        print(f"Debug - 完整历史记录-----: {all_moves}")

        # 获取引擎着法
        print("Debug - 开始引擎分析...")
        return self._get_engine_move(
            fen_str, all_moves, board_array, result, callback
        )

    def _handle_multi_step(self, pieces_array, result, callback):
        # 更新棋子位置
        if callback:
            callback(Message(
                MessageType.PIECES,
                "更新棋子位置",
                array=pieces_array
            ))

        # 处理多步变化
        self.history.clear()
        self.use_startpos = False
        fen_str, board_array = convert_array_to_fen(pieces_array, self.checker.is_red)
           
        # 获取引擎着法
        return self._get_engine_move(
            fen_str, None, board_array, result, callback
        )

    def _get_engine_move(self, fen_str, moves, board_array, check_result, callback) -> MoveResult:
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
            print(f"Debug - 引擎分析结果: move={move}, FEN={fen}")
            
            chinese_move = convert_move_to_chinese(move, board_array, self.checker.is_red)
            return MoveResult(
                move_text=Message(MessageType.MOVE_TEXT, chinese_move),
                move_code=Message(MessageType.MOVE_CODE, move, is_red=self.checker.is_red)
            )
            
        except Exception as e:
            print(f"引擎分析失败: {str(e)}")
            return MoveResult(
                move_text=Message(MessageType.STATUS, "引擎分析错误，请重试"),
                move_code=Message(MessageType.CHANGE, "", fen_str=fen_str, is_red=self.checker.is_red)
            )

    @classmethod
    def from_context(cls, context):
        """从全局上下文创建实例"""
        return cls(
            checker=context.checker,
            engine=context.engine,
            history=context.history,
            context=context
        )
