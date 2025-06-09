from chess import recognizer
from tools.utils import switch_to_fen, convert_move_to_chinese
from chess.engine import get_best_move
from chess.message import Message, MessageType
from chess.context import context

last_position = None

def main_process(img_origin, display_callback=None):  
    # 棋局图像  
    # img_path = './app/uploads/图像.jpeg' 

    # 识别棋盘
    x_array, y_array = recognizer.recognize_board(img_origin)

    # 识别棋子类型和坐标
    piecesArray, is_red = recognizer.recognize_pieces(img_origin, x_array, y_array, display_callback)


    # 棋子位置
    # position, is_red = recognition.calculate_pieces_position(x_array, y_array, piecesArray) # 按原始位置排列的二维数组

    # 检查局面是否变化
    # global last_position
    # if utils.check_repeat_position(position, last_position, is_red):
    #     return 'repeat'
    # last_position = position

    # 转成 FEN字符串
    fen_str, board_array = switch_to_fen(piecesArray, is_red)
    
    # 立即显示当前局面
    if display_callback:
        display_callback(Message(MessageType.BOARD_DISPLAY, "已获取局面...", fen_str=fen_str, is_red=is_red))

    # 向引擎发送命令
    move, fen = get_best_move(fen_str, is_red, display_callback)
    # move = 'h9g7'
    # fen = 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/RNBAKABNR w'
    print(f"Debug - Move : {move}, FEN: {fen}")  # 添加调试信息

    try:
        # 发送通知
        chinese_move = convert_move_to_chinese(move, board_array, is_red)
        return Message(MessageType.MOVE_TEXT, chinese_move), Message(MessageType.MOVE_CODE, move, fen_str=fen_str, is_red=is_red)
    except Exception as e:
        print(f"Error in convert_move_to_chinese: move={move}, error={str(e)}")  # 添加错误信息
        return Message(MessageType.STATUS, "识别错误，请重试"), Message(MessageType.BOARD_DISPLAY, "", fen_str=fen_str, is_red=is_red)


    
  