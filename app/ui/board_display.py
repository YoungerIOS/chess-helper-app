import os
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QPolygonF
from PySide6.QtCore import Qt, QRect, QPointF
import math

class BoardDisplay(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.pieces = []  # 存储当前棋盘上的棋子，每个元素是 (piece_type, x, y) 的元组
        self.board_size = (9, 10)  # 象棋棋盘大小：9列10行
        self.cell_size = 0  # 格子大小，将在resizeEvent中计算
        self.margin = 20  # 棋盘边距
        self.is_black_bottom = True  # 黑方是否在下方
        self.move_arrow = None  # 存储当前着法的箭头信息 (start_x, start_y, end_x, end_y)
        
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
        
        # 计算棋盘图片的缩放大小
        scaled_board = self.board_bg.scaled(
            self.width(), self.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        
        # 调整自身大小以匹配缩放后的棋盘图片
        self.setFixedHeight(scaled_board.height())
        
        # 计算格子大小
        self.cell_size = min(
            scaled_board.width() // self.board_size[0],
            scaled_board.height() // self.board_size[1]
        )
        
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
        y = 0  # 不再需要垂直居中，因为高度已经匹配
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
    
        # 绘制箭头
        if self.move_arrow:
            start_x, start_y, end_x, end_y = self.move_arrow
            # 计算箭头的实际坐标
            arrow_start_x = x + start_x * cell_width + cell_width // 2 + offset_x
            arrow_start_y = y + start_y * cell_height + cell_height // 2
            arrow_end_x = x + end_x * cell_width + cell_width // 2 + offset_x
            arrow_end_y = y + end_y * cell_height + cell_height // 2
            
            # 设置箭头样式
            pen = QPen(QColor(255, 0, 0, 180))  # 半透明红色
            pen.setWidth(3)
            painter.setPen(pen)
            
            # 绘制箭头线
            painter.drawLine(arrow_start_x, arrow_start_y, arrow_end_x, arrow_end_y)
            
            # 计算箭头头部
            angle = math.atan2(arrow_end_y - arrow_start_y, arrow_end_x - arrow_start_x)
            arrow_size = 15  # 箭头大小
            
            # 计算箭头头部的两个点
            arrow_head1 = QPointF(
                arrow_end_x - arrow_size * math.cos(angle - math.pi/6),
                arrow_end_y - arrow_size * math.sin(angle - math.pi/6)
            )
            arrow_head2 = QPointF(
                arrow_end_x - arrow_size * math.cos(angle + math.pi/6),
                arrow_end_y - arrow_size * math.sin(angle + math.pi/6)
            )
            
            # 绘制箭头头部
            arrow_head = QPolygonF([QPointF(arrow_end_x, arrow_end_y), arrow_head1, arrow_head2])
            painter.setBrush(QColor(255, 0, 0, 180))  # 半透明红色填充
            painter.drawPolygon(arrow_head)
    
    def update_board(self, fen_str, is_red=True, move=None):
        """根据FEN字符串更新棋盘显示"""
        print(f"Debug - update_board received is_red: {is_red}, fen_str: {fen_str}, move: {move}")
        self.pieces.clear()
        self.move_arrow = None  # 清除之前的箭头
        
        if not fen_str:
            return
            
        # 解析FEN字符串
        fen = fen_str.split()[0]
        rows = fen.split('/')
        
        # 根据红方位置调整行顺序
        if not is_red:  # 如果红方不在下方，需要反转行顺序
            rows.reverse()
            print("Debug - Reversing rows because is_red is False")
        
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
        
        # 处理着法代码
        if move and len(move) == 4:
            # 解析着法代码
            start_col = ord(move[0]) - ord('a')  # 将字母转换为0-8的数字
            start_row = int(move[1])
            end_col = ord(move[2]) - ord('a')
            end_row = int(move[3])
            
            # 注意：引擎使用的坐标系是从上到下0-9，从左到右a-i
            # 如果红方在上方，需要反转横坐标，以匹配棋子的显示
            if not is_red:
                start_col = 8 - start_col
                end_col = 8 - end_col
            else:
                # 如果红方在下方，需要反转纵坐标，因为引擎的坐标系是从上到下0-9
                start_row = 9 - start_row
                end_row = 9 - end_row
            
            print(f"Debug - Arrow coordinates: start({start_col}, {start_row}) -> end({end_col}, {end_row})")
            self.move_arrow = (start_col, start_row, end_col, end_row)
        
        self.update() 