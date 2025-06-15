import os
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QPolygonF, QTransform, QPainterPath
from PySide6.QtCore import Qt, QRect, QPointF, QTimer
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
        self.board_bg = QPixmap(os.path.join('app', 'images', 'media', 'chessboard.png'))
        
        # 加载棋子图片
        self.piece_images = {}
        self._load_piece_images()
        
        # 加载边框图片
        self.border_image = QPixmap(os.path.join('app', 'images', 'media', 'white_border.png'))
        
        # 加载变化标记图片
        self.bullseye_image = QPixmap(os.path.join('app', 'images', 'media', 'bullseye.png'))
        
        # 存储变化信息
        self.red_changes = []
        self.black_changes = []
        
        # 添加旋转动画相关属性
        self.rotation_angle = 0
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.update_rotation)
        self.animation_timer.start(50)  # 每50毫秒更新一次，即20帧每秒
        
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
        
        # 计算棋盘中心点
        center_x = x + scaled_board.width() // 2
        
        # 计算格子大小（使用8.8作为除数，让格子宽度略大一些）
        cell_width = scaled_board.width() / 8.875
        cell_height = scaled_board.height() // 10
        
        # 绘制变化标记
        for change in self.red_changes + self.black_changes:
            row, col, old_piece, new_piece = change
            # 计算位置（从中心点向两侧计算）
            offset_from_center = (col - 4) * cell_width  # 4是中心列的索引
            pos_x = center_x + offset_from_center
            pos_y = y + row * cell_height + cell_height // 2
            
            # 如果是起始位置（old_piece不是'-'），显示bullseye
            if old_piece != '-':
                scaled_bullseye = self.bullseye_image.scaled(
                    int(cell_width * 0.5),
                    int(cell_height * 0.5),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                bullseye_x = pos_x - scaled_bullseye.width() // 2
                bullseye_y = pos_y - scaled_bullseye.height() // 2
                painter.drawPixmap(bullseye_x, bullseye_y, scaled_bullseye)
            
            # 如果是终点位置（new_piece不是'-'），显示边框
            if new_piece != '-':
                scaled_border = self.border_image.scaled(
                    int(cell_width * 1.1),
                    int(cell_height * 1.1),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                border_x = pos_x - scaled_border.width() // 2
                border_y = pos_y - scaled_border.height() // 2
                painter.drawPixmap(border_x, border_y, scaled_border)
        
        # 绘制棋子
        for piece_type, pos_x, pos_y in self.pieces:
            if piece_type in self.piece_images:
                piece_img = self.piece_images[piece_type]
                # 计算棋子位置（从中心点向两侧计算）
                offset_from_center = (pos_x - 4) * cell_width  # 4是中心列的索引
                piece_x = center_x + offset_from_center
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
            # 计算箭头的实际坐标（从中心点向两侧计算）
            arrow_start_x = center_x + (start_x - 4) * cell_width
            arrow_start_y = y + start_y * cell_height + cell_height // 2
            arrow_end_x = center_x + (end_x - 4) * cell_width
            arrow_end_y = y + end_y * cell_height + cell_height // 2
            
            # 设置箭头样式
            pen = QPen(QColor(255, 0, 0, 180))  # 半透明红色
            pen.setWidth(3)
            painter.setPen(pen)
            
            # 计算箭头头部
            angle = math.atan2(arrow_end_y - arrow_start_y, arrow_end_x - arrow_start_x)
            arrow_size = 30  # 箭头大小
            
            # 计算箭头头部的点
            # 主箭头三角形的三个点
            arrow_tip = QPointF(arrow_end_x, arrow_end_y)
            
            # 计算箭头底边的两个端点（顶角45度）
            arrow_base1 = QPointF(
                arrow_end_x - arrow_size * math.cos(angle - math.pi/8),  # 22.5度
                arrow_end_y - arrow_size * math.sin(angle - math.pi/8)
            )
            arrow_base2 = QPointF(
                arrow_end_x - arrow_size * math.cos(angle + math.pi/8),  # 22.5度
                arrow_end_y - arrow_size * math.sin(angle + math.pi/8)
            )
            
            # 计算V形缺口的点
            # 缺口深度为箭头高度的一半
            notch_depth = arrow_size / 2
            
            # 计算缺口顶点（向箭头内部凹陷）
            notch_tip = QPointF(
                (arrow_base1.x() + arrow_base2.x()) / 2 + notch_depth * math.cos(angle),
                (arrow_base1.y() + arrow_base2.y()) / 2 + notch_depth * math.sin(angle)
            )
            
            # 计算直线终点（在箭头尖端之前停止）
            line_end = QPointF(
                arrow_end_x - arrow_size * 0.1 * math.cos(angle),  # 在尖端前10%的位置停止
                arrow_end_y - arrow_size * 0.1 * math.sin(angle)
            )
            
            # 计算箭头底边长度
            base_width = math.sqrt(
                (arrow_base2.x() - arrow_base1.x()) ** 2 +
                (arrow_base2.y() - arrow_base1.y()) ** 2
            )
            
            # 计算梯形上边宽度（箭头底边的60%）
            top_width = base_width * 0.6
            
            # 计算梯形的四个顶点
            # 上边中点（向箭头内部延伸30%）
            top_center = QPointF(
                (arrow_base1.x() + arrow_base2.x()) / 2 + arrow_size * 0.3 * math.cos(angle),
                (arrow_base1.y() + arrow_base2.y()) / 2 + arrow_size * 0.3 * math.sin(angle)
            )
            
            # 计算垂直于箭头方向的单位向量
            perp_x = -math.sin(angle)
            perp_y = math.cos(angle)
            
            # 计算上边两个端点（使用向量运算）
            top_left = QPointF(
                top_center.x() - top_width/2 * perp_x,
                top_center.y() - top_width/2 * perp_y
            )
            top_right = QPointF(
                top_center.x() + top_width/2 * perp_x,
                top_center.y() + top_width/2 * perp_y
            )
            
            # 计算下边两个端点（使用向量运算）
            line_width = 3  # 原来的线宽
            bottom_left = QPointF(
                arrow_start_x - line_width/2 * perp_x,
                arrow_start_y - line_width/2 * perp_y
            )
            bottom_right = QPointF(
                arrow_start_x + line_width/2 * perp_x,
                arrow_start_y + line_width/2 * perp_y
            )
            
            # 绘制梯形直线和三角形（使用单个路径）
            combined_path = QPainterPath()
            
            # 启用抗锯齿
            painter.setRenderHint(QPainter.Antialiasing)
            
            # 绘制梯形
            combined_path.moveTo(bottom_left)
            combined_path.lineTo(bottom_right)
            combined_path.lineTo(top_right)
            combined_path.lineTo(top_left)
            combined_path.lineTo(bottom_left)
            
            # 计算等腰三角形的顶点（90度顶角）
            # 计算梯形上边的中点
            triangle_base_center = QPointF(
                (top_left.x() + top_right.x()) / 2,
                (top_left.y() + top_right.y()) / 2
            )
            
            # 计算三角形的高度（使顶角为90度）
            # 对于等腰三角形，如果顶角为90度，则高度等于底边的一半
            triangle_height = top_width / 2
            
            # 计算三角形顶点（使用向量运算）
            triangle_apex = QPointF(
                triangle_base_center.x() + triangle_height * math.cos(angle),
                triangle_base_center.y() + triangle_height * math.sin(angle)
            )
            
            # 绘制等腰三角形
            combined_path.moveTo(top_left)
            combined_path.lineTo(triangle_apex)
            combined_path.lineTo(top_right)
            combined_path.lineTo(top_left)
            
            painter.setPen(QPen(QColor(255, 0, 0, 180), 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))  # 设置圆角连接
            painter.setBrush(QColor(255, 0, 0, 180))  # 半透明红色填充
            painter.drawPath(combined_path)
            
            # 使用QPainterPath绘制带缺口的箭头
            path = QPainterPath()
            path.moveTo(arrow_tip)  # 移动到箭头尖端
            path.lineTo(arrow_base1)  # 画到左底边
            path.lineTo(notch_tip)  # 画到缺口顶点
            path.lineTo(arrow_base2)  # 画到右底边
            path.lineTo(arrow_tip)  # 闭合路径
            
            painter.drawPath(path)
            
            # 在起始位置绘制旋转的边框图片
            border_size = int(cell_width * 1.1)  # 边框比棋子略大
            scaled_border = self.border_image.scaled(
                border_size,
                border_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            # 保存当前painter状态
            painter.save()
            
            # 设置旋转中心点
            transform = QTransform()
            transform.translate(arrow_start_x, arrow_start_y)
            transform.rotate(self.rotation_angle)
            transform.translate(-arrow_start_x, -arrow_start_y)
            painter.setTransform(transform)
            
            # 绘制旋转后的边框
            border_x = arrow_start_x - scaled_border.width() // 2
            border_y = arrow_start_y - scaled_border.height() // 2
            painter.drawPixmap(border_x, border_y, scaled_border)
            
            # 恢复painter状态
            painter.restore()
    
    def update_move_arrow(self, move, is_red):
        """更新着法箭头
        Args:
            move: 引擎返回的着法代码（如'e2e4'）
            is_red: 红方是否在下方
        """
        self.move_arrow = None
        if not move or len(move) != 4:
            return
            
        # 解析着法代码
        start_col = ord(move[0]) - ord('a')
        start_row = int(move[1])
        end_col = ord(move[2]) - ord('a')
        end_row = int(move[3])
        
        # 如果红方在上方，需要反转列坐标
        if not is_red:
            start_col = 8 - start_col
            end_col = 8 - end_col
        else:
            # 无论红方在上方还是下方，都需要反转行坐标
            start_row = 9 - start_row
            end_row = 9 - end_row
        
        self.move_arrow = (start_col, start_row, end_col, end_row)

    def update_pieces(self, piecesArray):
        """更新棋子位置
        Args:
            piecesArray: 与显示坐标完全相同的二维数组
        """
        # 清除箭头
        self.move_arrow = None
        
        self.pieces.clear()
        for y in range(10):
            for x in range(9):
                piece = piecesArray[y][x]
                if piece and piece != '-':
                    self.pieces.append((piece, x, y))

    def update_board_with_array(self, piecesArray, red_changes=None, black_changes=None):
        """使用数组更新棋盘显示
        Args:
            piecesArray: 与显示坐标完全相同的二维数组
            red_changes: 红方变化列表，使用显示坐标
            black_changes: 黑方变化列表，使用显示坐标
        """
        # 更新棋子位置（直接使用piecesArray）
        self.update_pieces(piecesArray)
        
        # 只更新有变化的一方的标记
        if red_changes is not None:
            self.red_changes = red_changes
        if black_changes is not None:
            self.black_changes = black_changes
        
        # 触发重绘
        self.update()

    # def update_board(self, fen_str, is_red=True, move=None, red_changes=None, black_changes=None):
    #     """根据FEN字符串更新棋盘显示"""
    #     print(f"Debug - update_board received is_red: {is_red}, fen_str: {fen_str}, move: {move}")
    #     self.pieces.clear()
    #     self.move_arrow = None  # 清除之前的箭头
    #     self.red_changes = []  # 存储红方变化
    #     self.black_changes = []  # 存储黑方变化
        
    #     # 处理变化标记的坐标转换
    #     if red_changes:
    #         for row, col, old_piece, new_piece in red_changes:
    #             if not is_red:  # 如果红方在上方，需要反转坐标
    #                 col = 8 - col
    #                 row = 9 - row
    #             self.red_changes.append((row, col, old_piece, new_piece))
                
    #     if black_changes:
    #         for row, col, old_piece, new_piece in black_changes:
    #             if not is_red:  # 如果红方在上方，需要反转坐标
    #                 col = 8 - col
    #                 row = 9 - row
    #             self.black_changes.append((row, col, old_piece, new_piece))
        
    #     if not fen_str:
    #         return
            
    #     # 解析FEN字符串
    #     fen = fen_str.split()[0]
    #     rows = fen.split('/')
        
    #     # 根据红方位置调整行顺序
    #     if not is_red:  # 如果红方不在下方，需要反转行顺序
    #         rows.reverse()
        
    #     for y, row in enumerate(rows):
    #         x = 0
    #         for char in row:
    #             if char.isdigit():
    #                 # 数字表示空格的个数
    #                 x += int(char)
    #             elif char.isalpha():
    #                 # 字母表示棋子
    #                 # 注意：FEN字符串中，大写字母表示红方，小写字母表示黑方
    #                 # 如果红方不在下方，需要反转x坐标
    #                 pos_x = 8 - x if not is_red else x
    #                 self.pieces.append((char, pos_x, y))
    #                 x += 1
    #             else:
    #                 # 忽略其他字符
    #                 continue
        
    #     # 处理着法代码
    #     if move and len(move) == 4:
    #         # 解析着法代码
    #         start_col = ord(move[0]) - ord('a')  # 将字母转换为0-8的数字
    #         start_row = int(move[1])
    #         end_col = ord(move[2]) - ord('a')
    #         end_row = int(move[3])
            
    #         # 注意：引擎使用的坐标系是从上到下0-9，从左到右a-i
    #         # 如果红方在上方，需要反转横坐标，以匹配棋子的显示
    #         if not is_red:
    #             start_col = 8 - start_col
    #             end_col = 8 - end_col
    #         else:
    #             # 如果红方在下方，需要反转纵坐标，因为引擎的坐标系是从上到下0-9
    #             start_row = 9 - start_row
    #             end_row = 9 - end_row
            
    #         print(f"Debug - Arrow coordinates: start({start_col}, {start_row}) -> end({end_col}, {end_row})")
    #         self.move_arrow = (start_col, start_row, end_col, end_row)
        
    #     self.update()
    
    def update_rotation(self):
        """更新旋转角度并触发重绘"""
        self.rotation_angle = (self.rotation_angle + 5) % 360  # 每次旋转5度
        self.update() 