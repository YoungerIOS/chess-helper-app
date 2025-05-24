import os
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import Qt, QRect

class BoardDisplay(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.pieces = []  # 存储当前棋盘上的棋子，每个元素是 (piece_type, x, y) 的元组
        self.board_size = (9, 10)  # 象棋棋盘大小：9列10行
        self.cell_size = 0  # 格子大小，将在resizeEvent中计算
        self.margin = 20  # 棋盘边距
        self.is_black_bottom = True  # 黑方是否在下方
        
        # 加载棋盘背景
        self.board_bg = QPixmap(os.path.join('app', 'images', 'media', 'chessboard.jpeg'))
        
        # 加载棋子图片
        self.piece_images = {}
        self._load_piece_images()
        
    def _load_piece_images(self):
        """加载所有棋子图片"""
        piece_types = {
            'K': 'red_K.png', 'k': 'black_k.png',  # 将/帅
            'A': 'red_A.png', 'a': 'black_a.png',  # 士/仕
            'B': 'red_B.png', 'b': 'black_b.png',  # 象/相
            'N': 'red_N.png', 'n': 'black_n.png',  # 马
            'R': 'red_R.png', 'r': 'black_r.png',  # 车
            'C': 'red_C.png', 'c': 'black_c.png',  # 炮
            'P': 'red_P.png', 'p': 'black_p.png'   # 兵/卒
        }
        
        for piece, filename in piece_types.items():
            path = os.path.join('app', 'images', 'media', filename)
            self.piece_images[piece] = QPixmap(path)
    
    def resizeEvent(self, event):
        """处理窗口大小改变事件"""
        super().resizeEvent(event)
        # 计算格子大小
        width = self.width() - 2 * self.margin
        height = self.height() - 2 * self.margin
        self.cell_size = min(width // self.board_size[0], height // self.board_size[1])
        self.update()
    
    def paintEvent(self, event):
        """绘制棋盘和棋子"""
        super().paintEvent(event)
        painter = QPainter(self)
        
        # 绘制棋盘背景
        scaled_board = self.board_bg.scaled(
            self.width(), self.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        x = (self.width() - scaled_board.width()) // 2
        y = (self.height() - scaled_board.height()) // 2
        painter.drawPixmap(x, y, scaled_board)
        
        # 计算实际的格子大小（基于缩放后的棋盘图片）
        cell_width = scaled_board.width() // self.board_size[0]
        cell_height = scaled_board.height() // self.board_size[1]
        
        # 计算偏移量（格子宽度的十分之一）
        offset_x = cell_width // 10
        
        # 绘制棋子
        for piece_type, pos_x, pos_y in self.pieces:
            if piece_type in self.piece_images:
                piece_img = self.piece_images[piece_type]
                # 计算棋子位置（放在格子正中间，并添加偏移量）
                piece_x = x + pos_x * cell_width + cell_width // 2 + offset_x
                piece_y = y + pos_y * cell_height + cell_height // 2
                
                # 缩放棋子图片，使其略小于格子
                scaled_piece = piece_img.scaled(
                    int(cell_width * 0.98),  # 棋子宽度为格子的98%
                    int(cell_height * 0.98),  # 棋子高度为格子的98%
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                
                # 居中显示棋子
                piece_x -= scaled_piece.width() // 2
                piece_y -= scaled_piece.height() // 2
                
                painter.drawPixmap(piece_x, piece_y, scaled_piece)
    
    def update_board(self, fen_str, is_red=True):
        """根据FEN字符串更新棋盘显示"""
        print(f"Debug - update_board received is_red: {is_red}, fen_str: {fen_str}")  # 添加调试信息
        self.pieces.clear()
        
        if not fen_str:
            return
            
        # 解析FEN字符串
        fen = fen_str.split()[0]
        rows = fen.split('/')
        
        # 根据红方位置调整行顺序
        if not is_red:  # 如果红方不在下方，需要反转行顺序
            rows.reverse()
            print("Debug - Reversing rows because is_red is False")  # 添加调试信息
        
        for y, row in enumerate(rows):
            x = 0
            for char in row:
                if char.isdigit():
                    # 数字表示空格的个数
                    x += int(char)
                elif char.isalpha():
                    # 字母表示棋子
                    # 注意：FEN字符串中，大写字母表示红方，小写字母表示黑方
                    # 如果红方不在下方，需要反转x坐标
                    pos_x = 8 - x if not is_red else x
                    self.pieces.append((char, pos_x, y))
                    x += 1
                else:
                    # 忽略其他字符
                    continue
        
        self.update() 