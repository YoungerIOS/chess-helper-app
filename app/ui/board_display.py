import os
import math
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QPolygonF, QTransform, QPainterPath
from PySide6.QtCore import Qt, QRect, QPointF, QTimer
from app.tools.utils import resource_path
from app.chess.context import context

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
        
        # 底图边框相对于单格的比例（左右与上下可能不同）；根据素材实测值
        self.border_ratio_x = 0.6  # 左/右边框厚度 = 0.6 * 单格宽
        self.border_ratio_y = 0.5   # 上/下边框厚度 = 0.5 * 单格高
        
        # 棋盘底图选项
        self.board_options = [
            resource_path('images', 'media', 'chessboard1.png'),
            resource_path('images', 'media', 'chessboard2.png'),
            resource_path('images', 'media', 'chessboard3.png'),
            resource_path('images', 'media', 'chessboard4.png'),
            resource_path('images', 'media', 'chessboard5.png')
        ]
        # 当前使用的棋盘索引（从上下文读取）
        self.current_board_index = getattr(context, 'board_index', 0)
        
        # 加载棋盘背景
        self.board_bg = QPixmap(self.board_options[self.current_board_index])
        
        # 加载棋子图片
        self.piece_images = {}
        self._load_piece_images()
        
        # 加载边框图片
        self.border_image = QPixmap(resource_path('images', 'media', 'piece_border.png'))
        
        # 加载变化标记图片
        self.bullseye_image = QPixmap(resource_path('images', 'media', 'bullseye.png'))
        
        # 存储移动信息
        self.move_from = None  # 起始位置 (row, col)
        self.move_to = None    # 目标位置 (row, col)
        
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
            path = resource_path('images', 'media', filename)
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
        
        # 计算内棋盘区域（四周边框为可配置比例的半格）
        width_units = 8.0 + 2.0 * self.border_ratio_x
        height_units = 9.0 + 2.0 * self.border_ratio_y
        cell_width = scaled_board.width() / width_units
        cell_height = scaled_board.height() / height_units
        inner_left = x + self.border_ratio_x * cell_width
        inner_top = y + self.border_ratio_y * cell_height
        
        # 绘制移动标记
        if self.move_from is not None and self.move_to is not None:
            # 绘制起始位置标记
            from_row, from_col = self.move_from
            from_x = inner_left + from_col * cell_width
            from_y = inner_top + from_row * cell_height
            
            # 绘制起始位置的bullseye
            scaled_bullseye = self.bullseye_image.scaled(
                int(round(cell_width * 0.45)),
                int(round(cell_height * 0.45)),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            bullseye_x = int(round(from_x - scaled_bullseye.width() / 2))
            bullseye_y = int(round(from_y - scaled_bullseye.height() / 2))
            painter.drawPixmap(bullseye_x, bullseye_y, scaled_bullseye)
            
            # 绘制目标位置标记
            to_row, to_col = self.move_to
            to_x = inner_left + to_col * cell_width
            to_y = inner_top + to_row * cell_height
            
            # 绘制目标位置的边框
            scaled_border = self.border_image.scaled(
                int(round(cell_width * 1.1)),
                int(round(cell_height * 1.1)),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            border_x = int(round(to_x - scaled_border.width() / 2))
            border_y = int(round(to_y - scaled_border.height() / 2))
            painter.drawPixmap(border_x, border_y, scaled_border)
        
        # 绘制棋子
        for piece_type, pos_x, pos_y in self.pieces:
            if piece_type in self.piece_images:
                piece_img = self.piece_images[piece_type]
                # 计算棋子中心（落点在交叉点）
                piece_cx = inner_left + pos_x * cell_width
                piece_cy = inner_top + pos_y * cell_height
                
                # 缩放棋子图片，使其略小于格子
                scaled_piece = piece_img.scaled(
                    int(round(cell_width * 0.98)),  # 棋子宽度为格子的98%
                    int(round(cell_height * 0.98)),  # 棋子高度为格子的98%
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                
                # 居中显示棋子
                draw_x = int(round(piece_cx - scaled_piece.width() / 2))
                draw_y = int(round(piece_cy - scaled_piece.height() / 2))
                
                painter.drawPixmap(draw_x, draw_y, scaled_piece)
        
        # 绘制箭头
        if self.move_arrow:
            start_x, start_y, end_x, end_y = self.move_arrow
            # 计算箭头的实际坐标（以交叉点为基准）
            arrow_start_x = inner_left + start_x * cell_width
            arrow_start_y = inner_top + start_y * cell_height
            arrow_end_x = inner_left + end_x * cell_width
            arrow_end_y = inner_top + end_y * cell_height
            
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
    
    def update_arrow(self, move, is_red):
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

    def update_pieces(self, array):
        """更新棋盘所有棋子位置
        Args:
            array: 与显示坐标完全相同的二维数组
        """
        # 清除箭头
        self.move_arrow = None
        self.move_from = None
        self.move_to = None
        
        self.pieces.clear()
        for y in range(10):
            for x in range(9):
                piece = array[y][x]
                if piece and piece != '-':
                    self.pieces.append((piece, x, y))

    def update_board(self, array, step_info=None):
        """更新棋盘(包括棋子位置和移动标记)
        Args:
            array: 与显示坐标完全相同的二维数组
            step_info: 着法信息，包含 from 和 to 坐标信息
        """
        # 更新棋子位置
        self.update_pieces(array)
        
        # 更新移动标记
        if step_info is not None and 'from_pos' in step_info and 'to_pos' in step_info:
            self.move_from = step_info['from_pos']
            self.move_to = step_info['to_pos']
        else:
            self.move_from = None
            self.move_to = None
        
        # 触发重绘
        self.update()

    def update_rotation(self):
        """更新旋转角度并触发重绘"""
        self.rotation_angle = (self.rotation_angle + 5) % 360  # 每次旋转5度
        self.update()
    
    def next_board(self):
        """切换到下一个棋盘底图并保存到配置"""
        self.current_board_index = (self.current_board_index + 1) % len(self.board_options)
        self.board_bg = QPixmap(self.board_options[self.current_board_index])
        # 保存到上下文
        context.board_index = self.current_board_index
        context.save_config()
        self.update()  # 立即重绘 