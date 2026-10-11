import os
import json
import threading
from typing import Optional, List
import cv2
import numpy as np
from flask import Flask, request, jsonify
from werkzeug.serving import make_server

from app.chess.context import context
from app.chess.board_locator import BoardLocator
from app.chess.recognizer import ChessRecognizer
from app.chess.engine import ChessEngine
from app.chess.message_bus import message_bus
from app.chess.message import Message, MessageType
from app.tools.utils import convert_array_to_fen, convert_move_to_chinese, convert_coords_to_move, app_data_path
from app.tools.log_config import get_logger

logger = get_logger(__name__)

app = Flask(__name__)

# 全局共享实例以复用模型和降低开销
recognizer = ChessRecognizer()
board_locator = BoardLocator()

# 初始开局棋盘摆位（用于判断是否为新对局）
START_RED = [
    ['r', 'n', 'b', 'a', 'k', 'a', 'b', 'n', 'r'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['-', 'c', '-', '-', '-', '-', '-', 'c', '-'],
    ['p', '-', 'p', '-', 'p', '-', 'p', '-', 'p'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['P', '-', 'P', '-', 'P', '-', 'P', '-', 'P'],
    ['-', 'C', '-', '-', '-', '-', '-', 'C', '-'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['R', 'N', 'B', 'A', 'K', 'A', 'B', 'N', 'R']
]
START_BLACK = [
    ['R', 'N', 'B', 'A', 'K', 'A', 'B', 'N', 'R'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['-', 'C', '-', '-', '-', '-', '-', 'C', '-'],
    ['P', '-', 'P', '-', 'P', '-', 'P', '-', 'P'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['p', '-', 'p', '-', 'p', '-', 'p', '-', 'p'],
    ['-', 'c', '-', '-', '-', '-', '-', 'c', '-'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['r', 'n', 'b', 'a', 'k', 'a', 'b', 'n', 'r']
]


def apply_move_to_board(board: list, move_str: str, is_red: bool = True) -> Optional[list]:
    """在棋盘二维数组上执行一步 UCI 着法 (例如 'h2e2')，返回新的棋盘数组副本"""
    if not move_str or len(move_str) != 4 or not board:
        return None
    try:
        col1 = ord(move_str[0]) - ord('a')
        row1 = int(move_str[1])
        col2 = ord(move_str[2]) - ord('a')
        row2 = int(move_str[3])
        if is_red:
            r1, c1 = 9 - row1, col1
            r2, c2 = 9 - row2, col2
        else:
            r1, c1 = row1, 8 - col1
            r2, c2 = row2, 8 - col2
            
        if not (0 <= r1 < 10 and 0 <= c1 < 9 and 0 <= r2 < 10 and 0 <= c2 < 9):
            return None
            
        new_board = [row[:] for row in board]
        piece = new_board[r1][c1]
        new_board[r1][c1] = '-'
        new_board[r2][c2] = piece
        return new_board
    except Exception:
        return None


def detect_single_move(board_old: list, board_new: list, is_red: bool = True) -> Optional[str]:
    """
    检测两个棋盘之间是否恰好只发生了一步单步移动。
    若是，返回其 UCI 格式的 move 字符串；否则返回 None。
    """
    if not board_old or not board_new or len(board_old) != 10 or len(board_new) != 10:
        return None
    diffs = []
    for r in range(10):
        for c in range(9):
            if board_old[r][c] != board_new[r][c]:
                diffs.append((r, c, board_old[r][c], board_new[r][c]))
                
    if len(diffs) != 2:
        return None
        
    src = None
    dst = None
    for r, c, old_p, new_p in diffs:
        if new_p == '-' and old_p != '-':
            src = (r, c)
        elif new_p != '-':
            dst = (r, c)
            
    if src and dst:
        return convert_coords_to_move(src, dst, is_red=is_red)
    return None


class MobileSession:
    """移动端协助自适应会话管理：负责常驻引擎调度、连贯步数跟踪与局面缓存"""
    def __init__(self):
        self.lock = threading.RLock()
        self.engine: Optional[ChessEngine] = None
        
        # 缓存状态
        self.last_board_array: Optional[list] = None
        self.last_is_red: Optional[bool] = None
        self.last_best_move_code: Optional[str] = None
        self.last_response: Optional[dict] = None
        
        # 自适应锚点与历史链条
        self.base_fen: Optional[str] = None
        self.moves_history: List[str] = []
        
    def get_or_start_engine(self) -> Optional[ChessEngine]:
        """获取常驻引擎实例，具备崩溃自愈和自动启动能力"""
        with self.lock:
            if self.engine is None or self.engine.process is None or self.engine.process.poll() is not None:
                logger.info("Initializing resident ChessEngine for Mobile API...")
                self.engine = ChessEngine(threads=2, hash_size=128)
                if not self.engine.start():
                    logger.error("Failed to start resident ChessEngine")
                    self.engine = None
                    return None
            return self.engine

    def stop_engine(self):
        """优雅关闭常驻引擎"""
        with self.lock:
            if self.engine is not None:
                try:
                    self.engine.quit()
                except Exception as e:
                    logger.warning(f"Error stopping mobile engine: {e}")
                self.engine = None
            self.reset_session()

    def reset_session(self):
        """重置会话缓存和历史"""
        self.last_board_array = None
        self.last_is_red = None
        self.last_best_move_code = None
        self.last_response = None
        self.base_fen = None
        self.moves_history = []


mobile_session = MobileSession()


@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({"status": "ok", "message": "ChessHelper Server is running"}), 200


@app.route('/api/heartbeat', methods=['POST', 'GET'])
def heartbeat():
    try:
        data = request.get_json(silent=True) or {}
        if not data and request.form:
            data = request.form.to_dict()
        if not data and request.args:
            data = request.args.to_dict()

        message_bus.publish(Message(MessageType.HEARTBEAT, "", **data))
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Heartbeat processing error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500



@app.route('/api/analyze', methods=['POST'])
def analyze_image():
    # 桌面分析与手机协助互斥：当桌面"开始"运行时，直接忽略分析请求，返回服务端正忙
    if context.is_desktop_running:
        logger.info("Desktop analysis is active. Ignoring mobile request (服务端正忙).")
        return jsonify({
            "success": False,
            "status": "busy",
            "message": "服务端正忙",
            "error": "服务端正忙",
            "move": "",
            "move_code": "",
            "fen": ""
        }), 200

    if 'image' not in request.files:
        return jsonify({
            "success": False,
            "status": "error",
            "message": "请上传棋盘截图",
            "error": "No image provided",
            "move": "",
            "move_code": "",
            "fen": ""
        }), 200
    
    file = request.files['image']
    
    try:
        npimg = np.frombuffer(file.read(), np.uint8)
        img_np = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
        if img_np is None:
            return jsonify({
                "success": False,
                "status": "error",
                "message": "图片格式无效或已损坏",
                "error": "Invalid image format",
                "move": "",
                "move_code": "",
                "fen": ""
            }), 200
            
        logger.info("Mobile API received an image.")
        
        # 使用图像的形状（宽高）作为缓存 Key
        img_shape = img_np.shape[:2]
        cache_key = str(img_shape)
        
        # 1. 静态图像定位棋盘 (带有分辨率缓存机制，避免重复霍夫圆检测)
        if 'BOARD_COORD_CACHE' not in app.config:
            app.config['BOARD_COORD_CACHE'] = {}
            cache_file = app_data_path("mobile_board_cache.json")
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r") as f:
                        app.config['BOARD_COORD_CACHE'] = json.load(f)
                except Exception:
                    pass

        if cache_key in app.config['BOARD_COORD_CACHE']:
            cached_data = app.config['BOARD_COORD_CACHE'][cache_key]
            x_array = cached_data['x_array']
            y_array = cached_data['y_array']
        else:
            x_array, y_array, board_rect = board_locator.locate_board_from_image(img_np)
            if x_array and y_array:
                app.config['BOARD_COORD_CACHE'][cache_key] = {
                    'x_array': x_array,
                    'y_array': y_array,
                    'board_rect': board_rect
                }
                try:
                    cache_file = app_data_path("mobile_board_cache.json")
                    with open(cache_file, "w") as f:
                        json.dump(app.config['BOARD_COORD_CACHE'], f)
                except Exception:
                    pass

        if not x_array or not y_array:
            logger.warning("Failed to locate chess board grid from image.")
            return jsonify({
                "success": False,
                "status": "error",
                "message": "未能在画面中识别到棋盘",
                "error": "Failed to locate chess board",
                "move": "",
                "move_code": "",
                "fen": ""
            }), 200
            
        # 2. 识别局面
        # recognize_piece_from_grid 内部将图像等比缩放到 800 宽，因此需要等比缩放网格坐标
        scale_factor = 800.0 / img_np.shape[1]
        scaled_x_array = [int(x * scale_factor) for x in x_array]
        scaled_y_array = [int(y * scale_factor) for y in y_array]
            
        board_array, _, _, _ = recognizer.recognize_piece_from_grid(img_np, scaled_x_array, scaled_y_array)
        
        # 检查是否为有效棋盘
        if not board_array:
            logger.warning("Failed to recognize board array from pieces.")
            return jsonify({
                "success": False,
                "status": "error",
                "message": "棋子特征识别失败",
                "error": "Failed to recognize pieces",
                "move": "",
                "move_code": "",
                "fen": ""
            }), 200
            
        # 由于用户视角在棋盘下方（i >= 5），在下半区统计红黑棋子的数量判断执红还是执黑
        red_count = 0
        black_count = 0
        for i in range(5, 10):
            for j in range(9):
                p = board_array[i][j]
                if p in ('R', 'N', 'B', 'A', 'K', 'C', 'P'):
                    red_count += 1
                elif p in ('r', 'n', 'b', 'a', 'k', 'c', 'p'):
                    black_count += 1
                    
        is_red = red_count >= black_count
        fen_str, _ = convert_array_to_fen(board_array, is_red=is_red)
        logger.info(f"Recognized FEN: {fen_str} (side={'red' if is_red else 'black'})")

        # 把手机端识别到的棋盘同步发布到电脑桌面 UI 上实时显示
        message_bus.publish(Message(MessageType.PIECES, "", array=board_array))
        
        # 3. 自适应锚点会话与常驻引擎调度
        with mobile_session.lock:
            # Case A: 局面完全相同 (防抖缓存，0ms 响应)
            if (mobile_session.last_board_array is not None 
                and mobile_session.last_board_array == board_array 
                and mobile_session.last_response is not None):
                logger.info("Identical board detected. Returning cached response (0ms).")
                if mobile_session.last_best_move_code:
                    message_bus.publish(Message(MessageType.MOVE_CODE, mobile_session.last_best_move_code, is_red=is_red))
                if mobile_session.last_response.get("move"):
                    message_bus.publish(Message(MessageType.MOVE_TEXT, mobile_session.last_response.get("move")))
                return jsonify(mobile_session.last_response), 200

            engine = mobile_session.get_or_start_engine()
            if not engine:
                return jsonify({
                    "success": False,
                    "status": "error",
                    "message": "象棋引擎启动异常",
                    "error": "Failed to start engine",
                    "move": "",
                    "move_code": "",
                    "fen": ""
                }), 200

            # 检查是否为新对局初始局面 (全盘 32 子初始阵型)
            is_initial_start = (board_array == START_RED or board_array == START_BLACK)
            if is_initial_start:
                logger.info("Initial starting position detected. Resetting session history.")
                mobile_session.reset_session()

            # Case B: 尝试连贯走步衔接 (连续求助场景)
            use_continuous_moves = False
            candidate_moves = []
            
            if (not is_initial_start 
                and mobile_session.last_board_array is not None 
                and mobile_session.last_is_red == is_red 
                and mobile_session.last_best_move_code 
                and mobile_session.base_fen):
                
                # 检查用户是否执行了上一手推荐着法
                board_after_my_move = apply_move_to_board(
                    mobile_session.last_board_array, 
                    mobile_session.last_best_move_code, 
                    is_red
                )
                if board_after_my_move is not None:
                    # 检测对方是否应了一步合法走法
                    opp_move = detect_single_move(board_after_my_move, board_array, is_red)
                    if opp_move:
                        candidate_moves = list(mobile_session.moves_history)
                        candidate_moves.append(mobile_session.last_best_move_code)
                        candidate_moves.append(opp_move)
                        use_continuous_moves = True
                        logger.info(f"Continuous move progression detected: +{mobile_session.last_best_move_code} +{opp_move}")

            # 解析可能存在的 param 字段 (手机客户端传来的可选计算参数)
            go_param = 'movetime'
            go_value = '500'
            param_str = request.form.get('param')
            if param_str:
                try:
                    params_dict = json.loads(param_str)
                    if 'goParam' in params_dict:
                        go_param = params_dict['goParam']
                        go_value = str(params_dict.get(go_param, '500'))
                    elif 'movetime' in params_dict:
                        go_param = 'movetime'
                        go_value = str(params_dict['movetime'])
                    elif 'depth' in params_dict:
                        go_param = 'depth'
                        go_value = str(params_dict['depth'])
                    logger.info(f"Using remote engine params: {go_param}={go_value}")
                except Exception as e:
                    logger.warning(f"Failed to parse param json: {e}")

            best_move = ""
            best_move_code = ""
            best_move_text = ""

            # 优先尝试连贯模式（防长将判负 + 深度搜索累积）
            if use_continuous_moves and candidate_moves and mobile_session.base_fen:
                try:
                    moves_str = " ".join(candidate_moves)
                    best_move, _, _ = engine.get_bestmove(
                        fen=mobile_session.base_fen,
                        side=is_red,
                        is_newgame=False,
                        use_startpos=False,
                        moves=moves_str,
                        go_param=go_param,
                        go_value=go_value
                    )
                    if best_move:
                        mobile_session.moves_history = candidate_moves
                except Exception as e:
                    logger.warning(f"Continuous engine evaluation failed ({e}), falling back to pure FEN mode")
                    best_move = ""

            # Case C: 断层跳步 / 初次截图 / 异常降级兜底 (纯当前 FEN 模式，重设锚点)
            if not best_move:
                mobile_session.base_fen = fen_str
                mobile_session.moves_history = []
                best_move, _, _ = engine.get_bestmove(
                    fen=fen_str,
                    side=is_red,
                    is_newgame=is_initial_start,
                    use_startpos=False,
                    go_param=go_param,
                    go_value=go_value
                )

            if best_move:
                best_move_code = best_move
                chinese_move = convert_move_to_chinese(best_move, board_array, is_red)
                if chinese_move:
                    best_move_text = chinese_move

                # 同步将走法箭头与文字发布到电脑 UI
                message_bus.publish(Message(MessageType.MOVE_CODE, best_move_code, is_red=is_red))
                message_bus.publish(Message(MessageType.MOVE_TEXT, best_move_text))

            if not best_move_text:
                return jsonify({
                    "success": False,
                    "status": "error",
                    "message": "未能计算出有效走法",
                    "error": "Could not find a valid move",
                    "move": "",
                    "move_code": "",
                    "fen": fen_str
                }), 200

            logger.info(f"Best move found: {best_move_text} ({best_move_code})")
            success_response = {
                "success": True,
                "status": "success",
                "message": "分析成功",
                "move": best_move_text,
                "move_code": best_move_code,
                "fen": fen_str,
                "error": ""
            }

            # 更新会话缓存
            mobile_session.last_board_array = [row[:] for row in board_array]
            mobile_session.last_is_red = is_red
            mobile_session.last_best_move_code = best_move_code
            mobile_session.last_response = success_response

            return jsonify(success_response), 200

    except Exception as e:
        logger.error(f"Mobile API Error: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "status": "error",
            "message": f"处理异常: {str(e)}",
            "error": str(e),
            "move": "",
            "move_code": "",
            "fen": ""
        }), 200


class MobileServerThread(threading.Thread):
    """手机协助后端服务守护线程 (Werkzeug 多线程轻量 HTTP 服务)"""
    def __init__(self, host='0.0.0.0', port=5050):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.server = None
        
    def run(self):
        # 随服务启动预热常驻引擎
        mobile_session.get_or_start_engine()
        self.server = make_server(self.host, self.port, app, threaded=True)
        logger.info(f"Mobile API Server started on {self.host}:{self.port}")
        self.server.serve_forever()
        
    def stop(self):
        if self.server:
            self.server.shutdown()
            logger.info("Mobile API Server stopped")
        # 服务关闭时清理常驻引擎和会话
        mobile_session.stop_engine()
