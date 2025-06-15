from chess import recognizer
from tools.utils import convert_array_to_fen, convert_move_to_chinese
from chess.engine import get_best_move
from chess.message import Message, MessageType
from chess.context import context
import time

def main_process(img_origin, callback=None):  
    # 棋局图像  
    # img_path = './app/uploads/图像.jpeg' 

    # 识别棋盘
    x_array, y_array = recognizer.recognize_board(img_origin)

    # 识别棋子类型和坐标
    piecesArray, is_red = recognizer.recognize_piece_from_grid(img_origin, x_array, y_array, callback)
    
    # 如果识别失败，返回空消息
    if piecesArray is None:
        time.sleep(0.5)
        print("Debug - 识别棋子失败，等待0.5秒后返回重试")
        return None, Message(MessageType.MOVE_CODE, "")
    

    print("Debug - 棋子数组:")
    for row in piecesArray:
        print(row)
    
    # 检查局面是否有变化
    has_changes, red_changes, black_changes = context.position_checker.get_available_changes(piecesArray)
    print(f"Debug - 局面检查: has_changes={has_changes}, red_changes={red_changes}, black_changes={black_changes}")
    
    # 如果有变化，更新局面显示
    if has_changes:
        if callback:
            callback(Message(
                MessageType.CHANGE, 
                "已获取局面...", 
                position=piecesArray, 
                is_red=is_red,
                red_changes=red_changes,
                black_changes=black_changes
            ))
        
        # 判断是否是对方走棋（我方是红棋，黑方有变化；我方是黑棋，红方有变化）
        # 或者是初始局面（没有变化列表）
        is_opponent_move = (is_red and black_changes) or (not is_red and red_changes) or (is_red and not red_changes and not black_changes)
        print(f"Debug - 引擎分析判断: is_red={is_red}, is_opponent_move={is_opponent_move}")
        
        if is_opponent_move:
            print("Debug - 开始引擎分析...")
            # 转成 FEN字符串
            fen_str, board_array = convert_array_to_fen(piecesArray, is_red)
            # 对方已走棋，轮到我方，发送给引擎计算
            move, fen = get_best_move(fen_str, is_red, callback)
            print(f"Debug - 引擎分析结果: move={move}, FEN={fen}")

            try:
                # 发送通知
                chinese_move = convert_move_to_chinese(move, board_array, is_red)
                return Message(MessageType.MOVE_TEXT, chinese_move), Message(MessageType.MOVE_CODE, move, is_red=is_red)
            except Exception as e:
                print(f"Error in convert_move_to_chinese: move={move}, error={str(e)}")  # 添加错误信息
                return Message(MessageType.STATUS, "识别错误，请重试"), Message(MessageType.CHANGE, "", fen_str=fen_str, is_red=is_red)
    
    # 局面未变化或不是对方走棋，返回空着法
    return Message(MessageType.MOVE_TEXT, ""), Message(MessageType.MOVE_CODE, "")


    
  