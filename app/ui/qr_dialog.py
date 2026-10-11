import json
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QApplication, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QPixmap, QFont, QPainter, QColor, QMouseEvent
from app.tools.log_config import get_logger

logger = get_logger(__name__)

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


class QRCodeDialog(QDialog):
    """手机协助连接纯净无边框卡片面板 (全自动静默无感双通道)"""
    
    def __init__(self, ip: str, port: int = 5050, pairing_id: str = "CHESS-DEFAULT", 
                 tunnel_url: str = None, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.port = port
        self.pairing_id = pairing_id
        self.tunnel_url = tunnel_url
        self.lan_api_url = f"http://{self.ip}:{port}/api/analyze"
        
        # 1. 无边框纯净卡片，去除系统标题栏与操作按钮
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        # 紧凑精致面板尺寸
        self.setFixedSize(320, 365)
        self._drag_pos = None
        
        self._init_ui()
        
    def _init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(15, 15, 15, 15)
        outer_layout.setSpacing(0)
        
        # 主卡片容器
        self.card = QFrame()
        self.card.setObjectName("qrCard")
        self.card.setStyleSheet("""
            QFrame#qrCard {
                background-color: #FFFFFF;
                border-radius: 16px;
                border: 1px solid #E2E8F0;
            }
        """)
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 45))
        shadow.setOffset(0, 5)
        self.card.setGraphicsEffect(shadow)
        
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(18, 16, 18, 18)
        card_layout.setSpacing(12)
        
        # 1. 顶部自定义标题栏 (标题 + 右上角极简关闭图标)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel("打开手机 App 扫码连接")
        title_label.setFont(QFont("Arial", 13, QFont.Bold))
        title_label.setStyleSheet("color: #1E293B; border: none; background: transparent;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # 右上角放大款极简关闭按钮
        self.close_icon_btn = QPushButton("✕")
        self.close_icon_btn.setObjectName("closeIconBtn")
        self.close_icon_btn.setFixedSize(30, 30)
        self.close_icon_btn.setCursor(Qt.PointingHandCursor)
        self.close_icon_btn.setStyleSheet("""
            QPushButton#closeIconBtn {
                background-color: transparent;
                color: #94A3B8;
                font-size: 15px;
                font-weight: bold;
                border: none;
                border-radius: 15px;
            }
            QPushButton#closeIconBtn:hover {
                background-color: #F1F5F9;
                color: #1E293B;
            }
            QPushButton#closeIconBtn:pressed {
                background-color: #E2E8F0;
                color: #0F172A;
            }
        """)
        self.close_icon_btn.clicked.connect(self.close)
        header_layout.addWidget(self.close_icon_btn)
        
        card_layout.addLayout(header_layout)
        
        # 2. 二维码居中容器
        qr_container = QFrame()
        qr_container.setFixedSize(210, 210)
        qr_container.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #F1F5F9;
                border-radius: 12px;
            }
        """)
        qr_layout = QVBoxLayout(qr_container)
        qr_layout.setContentsMargins(5, 5, 5, 5)
        qr_layout.setAlignment(Qt.AlignCenter)
        
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(200, 200)
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setStyleSheet("background: transparent; border: none;")
        
        self._render_qr_code()
        
        qr_layout.addWidget(self.qr_label)
        
        qr_center_layout = QHBoxLayout()
        qr_center_layout.addStretch()
        qr_center_layout.addWidget(qr_container)
        qr_center_layout.addStretch()
        card_layout.addLayout(qr_center_layout)
        
        # 3. 底部按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.copy_btn = QPushButton("复制地址")
        self.copy_btn.setFixedHeight(34)
        self.copy_btn.setFont(QFont("Arial", 10))
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #F8FAFC;
                color: #475569;
                border-radius: 8px;
                border: 1px solid #E2E8F0;
                padding: 6px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #F1F5F9;
                color: #1E293B;
            }
            QPushButton:pressed {
                background-color: #E2E8F0;
            }
        """)
        self.copy_btn.clicked.connect(self._on_copy_url)
        btn_layout.addWidget(self.copy_btn)
        
        self.close_btn = QPushButton("完成")
        self.close_btn.setFixedHeight(34)
        self.close_btn.setFont(QFont("Arial", 10))
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border-radius: 8px;
                border: none;
                padding: 6px 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
            QPushButton:pressed {
                background-color: #1D4ED8;
            }
        """)
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)
        
        card_layout.addLayout(btn_layout)
        outer_layout.addWidget(self.card)

    def update_tunnel_url(self, tunnel_url: str):
        """静默更新外网隧道 URL 并重新绘制综合二维码"""
        self.tunnel_url = tunnel_url
        self._render_qr_code()

    def _get_qr_payload(self) -> str:
        """生成用于手机端识别的综合配对 JSON 载荷"""
        payload = {
            "pid": self.pairing_id,
            "lan": self.lan_api_url,
            "wan": f"{self.tunnel_url}/api/analyze" if self.tunnel_url else ""
        }
        return json.dumps(payload, separators=(',', ':'))

    def _render_qr_code(self):
        """生成并渲染二维码"""
        payload = self._get_qr_payload()
        if HAS_QRCODE:
            try:
                qr = qrcode.QRCode(
                    version=None,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=10,
                    border=2,
                )
                qr.add_data(payload)
                qr.make(fit=True)
                matrix = qr.get_matrix()
                
                pixmap = self._matrix_to_pixmap(matrix, 200)
                self.qr_label.setPixmap(pixmap)
                return
            except Exception as e:
                logger.error(f"Error generating QR with qrcode library: {e}")

        self._render_placeholder()

    def _matrix_to_pixmap(self, matrix, size: int) -> QPixmap:
        """将布尔矩阵以 QPainter 绘制为矢量级清晰度的 QPixmap"""
        n = len(matrix)
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor("#FFFFFF"))
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#0F172A"))
        
        cell_size = size / n
        for r in range(n):
            for c in range(n):
                if matrix[r][c]:
                    x = int(c * cell_size)
                    y = int(r * cell_size)
                    w = int((c + 1) * cell_size) - x
                    h = int((r + 1) * cell_size) - y
                    painter.drawRect(x, y, w, h)
                    
        painter.end()
        return pixmap

    def _render_placeholder(self):
        self.qr_label.setText(
            "<div style='text-align: center;'>"
            "<b style='color: #334155;'>未检测到二维码模块</b><br><br>"
            "<span style='color: #64748B; font-size: 11px;'>"
            "终端运行:<br><code>pip install qrcode</code></span>"
            "</div>"
        )
        self.qr_label.setWordWrap(True)

    def _on_copy_url(self):
        clipboard = QApplication.clipboard()
        # 复制地址
        target_copy = f"{self.tunnel_url}/api/analyze" if self.tunnel_url else self.lan_api_url
        clipboard.setText(target_copy)
        
        original_text = self.copy_btn.text()
        self.copy_btn.setText("✓ 已复制")
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border-radius: 8px;
                border: none;
                padding: 6px 14px;
                font-weight: 500;
            }
        """)
        QTimer.singleShot(1800, lambda: self._reset_copy_btn(original_text))

    def _reset_copy_btn(self, text):
        self.copy_btn.setText(text)
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #F8FAFC;
                color: #475569;
                border-radius: 8px;
                border: 1px solid #E2E8F0;
                padding: 6px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #F1F5F9;
                color: #1E293B;
            }
            QPushButton:pressed {
                background-color: #E2E8F0;
            }
        """)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
