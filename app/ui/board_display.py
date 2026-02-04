from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QStackedLayout
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QPolygonF, QTransform, QPainterPath
from PySide6.QtCore import Qt, QRect, QPointF, QTimer, QSize
from app.tools.utils import resource_path
from app.chess.context import context
import os
import math

class BoardCanvas(QLabel):
    """
    负责具体棋盘内容绘制的画布组件
    (原 BoardDisplay 的核心逻辑)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        # 设置焦点策略，确保能接收键盘事件
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_Hover)
        
        # 移除之前的 inset_padding，改为四向边距控制
        # 这些边距是为了适配 boardShell 的 padding (QSS) + boardInset 的 visual gap
        # Shell QSS: border 1.5px, padding: 3px 8px 8px 8px
        # Total Shell Offset: Top ~4.5px, Others ~9.5px
        # + Visual Gap (4px)
        # + User requested shrink (5px per side)
        self.margin_top = 11   # 9 + 5
        self.margin_left = 24  # 14 + 5
        self.margin_right = 24 # 14 + 5
        self.margin_bottom = 21 # 32 -> 26
        
        self.pieces = []  # 存储当前棋盘上的棋子
        self.board_size = (9, 10)  # 象棋棋盘大小
        self.cell_size = 0  
        self.margin = 20  
        self.is_black_bottom = True  
        self.move_arrow = None  
        
        # 边框比例
        self.border_ratio_x = 0.2  # 0.2
        self.border_ratio_y = 0.2  # 0.2
        
        # 棋盘底图选项
        self.board_options = [
            resource_path('images', 'media', 'chessboard3.png'),
            resource_path('images', 'media', 'chessboard4.png'),
            resource_path('images', 'media', 'chessboard5.png')
        ]
        self.current_board_index = getattr(context, 'board_index', 0)
        # 防止索引越界 (如果配置文件存的是旧索引)
        if self.current_board_index >= len(self.board_options):
            self.current_board_index = 0
            
        self.board_bg = QPixmap(self.board_options[self.current_board_index])
        
        self.piece_images = {}
        self._load_piece_images()
        self.border_image = QPixmap(resource_path('images', 'media', 'piece_border.png'))
        self.bullseye_image = QPixmap(resource_path('images', 'media', 'bullseye.png'))
        
        self.move_from = None  
        self.move_to = None    
        
        self.rotation_angle = 0
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.update_rotation)
        self.animation_timer.start(50)  
        
    def _load_piece_images(self):
        """加载所有棋子图片"""
        piece_types = {
            'K': 'red_K.png', 'k': 'black_k.png',
            'A': 'red_A.png', 'a': 'black_a.png',
            'B': 'red_B.png', 'b': 'black_b.png',
            'N': 'red_N.png', 'n': 'black_n.png',
            'R': 'red_R.png', 'r': 'black_r.png',
            'C': 'red_C.png', 'c': 'black_c.png',
            'P': 'red_P.png', 'p': 'black_p.png'
        }
        
        for piece, filename in piece_types.items():
            path = resource_path('images', 'media', filename)
            self.piece_images[piece] = QPixmap(path)
    
    def resizeEvent(self, event):
        """处理窗口大小改变事件"""
        super().resizeEvent(event)
        
        # 计算绘制区域 (扣除边距)
        target_w = max(1, self.width() - self.margin_left - self.margin_right)
        target_h = max(1, self.height() - self.margin_top - self.margin_bottom)
        
        scaled_board = self.board_bg.scaled(
            target_w, target_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        
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
        
        # 计算绘制区域
        target_w = max(1, self.width() - self.margin_left - self.margin_right)
        target_h = max(1, self.height() - self.margin_top - self.margin_bottom)
        
        scaled_board = self.board_bg.scaled(
            target_w, target_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        
        # 居中逻辑：基于边距偏移 + 剩余空间居中
        # 1. 在有效区域内居中
        content_x = (target_w - scaled_board.width()) // 2
        content_y = (target_h - scaled_board.height()) // 2
        
        # 2. 加上起始偏移
        x = self.margin_left + content_x
        y = self.margin_top + content_y
        
        # 根据需求绘制底图
        painter.drawPixmap(x, y, scaled_board)
        
        # 计算内棋盘区域（四周边框为可配置比例的半格）
        width_units = 8.0 + 2.0 * self.border_ratio_x
        height_units = 9.0 + 2.0 * self.border_ratio_y
        cell_width = scaled_board.width() / width_units
        cell_height = scaled_board.height() / height_units
        inner_left = x + self.border_ratio_x * cell_width
        inner_top = y + self.border_ratio_y * cell_height
        
        # ... (后续绘制棋子、标记的逻辑保持不变)
        
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
                    int(round(cell_width * 0.98)),  # 棋子宽度为格子的90% (原98%)
                    int(round(cell_height * 0.98)),  # 棋子高度为格子的90% (原98%)
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                
                # 居中显示棋子
                draw_x = int(round(piece_cx - scaled_piece.width() / 2))
                draw_y = int(round(piece_cy - scaled_piece.height() / 2))
                
                painter.drawPixmap(draw_x, draw_y, scaled_piece)
        
        # 绘制箭头
        if self.move_arrow:
            (start_row, start_col), (end_row, end_col) = self.move_arrow
            # 计算箭头的实际坐标（以交叉点为基准）
            arrow_start_x = inner_left + start_col * cell_width
            arrow_start_y = inner_top + start_row * cell_height
            arrow_end_x = inner_left + end_col * cell_width
            arrow_end_y = inner_top + end_row * cell_height
            
            # 设置箭头样式
            pen = QPen(QColor(255, 0, 0, 180))  # 半透明红色
            pen.setWidth(3)
            painter.setPen(pen)
            
            # 计算箭头头部
            angle = math.atan2(arrow_end_y - arrow_start_y, arrow_end_x - arrow_start_x)
            arrow_size = 30  # 箭头大小
            
            # 计算箭头头部的点
            arrow_tip = QPointF(arrow_end_x, arrow_end_y)
            arrow_base1 = QPointF(
                arrow_end_x - arrow_size * math.cos(angle - math.pi/8),
                arrow_end_y - arrow_size * math.sin(angle - math.pi/8)
            )
            arrow_base2 = QPointF(
                arrow_end_x - arrow_size * math.cos(angle + math.pi/8),
                arrow_end_y - arrow_size * math.sin(angle + math.pi/8)
            )
            notch_depth = arrow_size / 2
            notch_tip = QPointF(
                (arrow_base1.x() + arrow_base2.x()) / 2 + notch_depth * math.cos(angle),
                (arrow_base1.y() + arrow_base2.y()) / 2 + notch_depth * math.sin(angle)
            )
            
            # 计算底边宽度、梯形上边宽度等
            base_width = math.sqrt((arrow_base2.x() - arrow_base1.x())**2 + (arrow_base2.y() - arrow_base1.y())**2)
            top_width = base_width * 0.6
            top_center = QPointF(
                (arrow_base1.x() + arrow_base2.x()) / 2 + arrow_size * 0.3 * math.cos(angle),
                (arrow_base1.y() + arrow_base2.y()) / 2 + arrow_size * 0.3 * math.sin(angle)
            )
            perp_x = -math.sin(angle)
            perp_y = math.cos(angle)
            top_left = QPointF(top_center.x() - top_width/2 * perp_x, top_center.y() - top_width/2 * perp_y)
            top_right = QPointF(top_center.x() + top_width/2 * perp_x, top_center.y() + top_width/2 * perp_y)
            
            line_width = 3
            bottom_left = QPointF(arrow_start_x - line_width/2 * perp_x, arrow_start_y - line_width/2 * perp_y)
            bottom_right = QPointF(arrow_start_x + line_width/2 * perp_x, arrow_start_y + line_width/2 * perp_y)
            
            combined_path = QPainterPath()
            painter.setRenderHint(QPainter.Antialiasing)
            combined_path.moveTo(bottom_left)
            combined_path.lineTo(bottom_right)
            combined_path.lineTo(top_right)
            combined_path.lineTo(top_left)
            combined_path.lineTo(bottom_left)
            
            triangle_base_center = QPointF((top_left.x() + top_right.x())/2, (top_left.y() + top_right.y())/2)
            triangle_height = top_width / 2
            triangle_apex = QPointF(triangle_base_center.x() + triangle_height * math.cos(angle), triangle_base_center.y() + triangle_height * math.sin(angle))
            
            combined_path.moveTo(top_left)
            combined_path.lineTo(triangle_apex)
            combined_path.lineTo(top_right)
            combined_path.lineTo(top_left)
            
            painter.setPen(QPen(QColor(255, 0, 0, 180), 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(QColor(255, 0, 0, 180))
            painter.drawPath(combined_path)
            
            path = QPainterPath()
            path.moveTo(arrow_tip)
            path.lineTo(arrow_base1)
            path.lineTo(notch_tip)
            path.lineTo(arrow_base2)
            path.lineTo(arrow_tip)
            painter.drawPath(path)
            
            # 旋转边框
            border_size = int(cell_width * 1.1)
            scaled_border = self.border_image.scaled(border_size, border_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.save()
            transform = QTransform()
            transform.translate(arrow_start_x, arrow_start_y)
            transform.rotate(self.rotation_angle)
            transform.translate(-arrow_start_x, -arrow_start_y)
            painter.setTransform(transform)
            border_x = arrow_start_x - scaled_border.width() // 2
            border_y = arrow_start_y - scaled_border.height() // 2
            painter.drawPixmap(int(border_x), int(border_y), scaled_border)
            painter.restore()
            
    def update_arrow(self, move, is_red):
        self.move_arrow = None
        if not move or len(move) != 4: return
        start_col = ord(move[0]) - ord('a')
        start_row = int(move[1])
        end_col = ord(move[2]) - ord('a')
        end_row = int(move[3])
        if not is_red:
            start_col = 8 - start_col
            end_col = 8 - end_col
        else:
            start_row = 9 - start_row
            end_row = 9 - end_row
        self.move_arrow = ((start_row, start_col), (end_row, end_col)) # Fixed type to tuple of tuples
        self.update()

    def update_pieces(self, array):
        new_pieces = []
        for y in range(10):
            for x in range(9):
                piece = array[y][x]
                if piece and piece != '-': new_pieces.append((piece, x, y))
        if self.pieces == new_pieces: return
        self.move_arrow = None
        self.move_from = None
        self.move_to = None
        self.pieces = new_pieces
        self.update()

    def update_board(self, array, step_info=None):
        self.update_pieces(array)
        if step_info and 'from_pos' in step_info and 'to_pos' in step_info:
            self.move_from = step_info['from_pos']
            self.move_to = step_info['to_pos']
        else:
            self.move_from = None
            self.move_to = None
        self.update()

    def update_rotation(self):
        self.rotation_angle = (self.rotation_angle + 5) % 360
        self.update()
    
    def next_board(self):
        self.current_board_index = (self.current_board_index + 1) % len(self.board_options)
        self.board_bg = QPixmap(self.board_options[self.current_board_index])
        context.board_index = self.current_board_index
        context.save_config()
        self.update()
    
    def clear_board(self):
        self.pieces = []
        self.move_arrow = None
        self.move_from = None
        self.move_to = None
        self.update()


class BoardDisplay(QWidget):
    """
    结构化棋盘容器
    层级：BoardDisplay -> [boardShell(Layer 0), BoardCanvas(Layer 1)]
    采用层叠布局 (QStackedLayout):
    Layer 0: Shell (含 Inset) - 负责背景视觉
    Layer 1: Canvas - 负责顶层绘制 (图片+棋子)，覆盖在 Shell 之上以防止 clipping
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 改用 QStackedLayout 以便让 Canvas 覆盖在 Shell/Inset 之上
        self.layout = QStackedLayout(self)
        self.layout.setStackingMode(QStackedLayout.StackAll)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. 外壳层 (Wood/Frame)
        self.board_shell = QFrame()
        self.shell_layout = QVBoxLayout(self.board_shell)
        self.shell_layout.setContentsMargins(0, 0, 0, 0)
        self.board_shell.setObjectName("boardShell")
        
        # 2. 内嵌层 (Shadow/Depth) - 作为 Shell 的子元素
        self.board_inset = QFrame()
        self.inset_layout = QVBoxLayout(self.board_inset)
        self.inset_layout.setContentsMargins(0, 0, 0, 0)
        self.board_inset.setObjectName("boardInset")
        
        # 组装背景层
        self.shell_layout.addWidget(self.board_inset)
        
        # 3. 画布层 (Content) - 独立的一层，覆盖在上方
        self.board_canvas = BoardCanvas()
        self.board_canvas.setStyleSheet("background-color: transparent;") 
        
        # 组装层叠布局
        # Layer 0: Shell (Bottom)
        self.layout.addWidget(self.board_shell)
        # Layer 1: Canvas (Top)
        self.layout.addWidget(self.board_canvas)
        
        # 强制将 Canvas 置于顶层
        self.layout.setCurrentWidget(self.board_canvas)
        self.board_canvas.raise_()

    # 代理方法，让外部调用像以前一样
    def update_board(self, *args, **kwargs):
        self.board_canvas.update_board(*args, **kwargs)
        
    def next_board(self):
        self.board_canvas.next_board()
        
    def clear_board(self):
        self.board_canvas.clear_board()
        
    def update_arrow(self, *args, **kwargs):
        self.board_canvas.update_arrow(*args, **kwargs)