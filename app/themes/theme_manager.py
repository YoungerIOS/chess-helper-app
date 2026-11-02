import os
import re
from PySide6.QtWidgets import QApplication
from app.tools.utils import resource_path
from app.tools.log_config import get_logger

logger = get_logger(__name__)

class ThemeManager:
    """
    UI 主题管理器
    保持原生沉浸式拟物机甲深色风格（背景色 #212123）
    """
    
    THEME_DARK = "dark"
    COLOR_DARK_BG = "#212123"

    @staticmethod
    def load_stylesheet() -> str:
        """加载暗色 QSS 样式表，并将图片相对路径转换为可跨目录执行的绝对路径"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        dark_qss_path = os.path.join(current_dir, "dark.qss")
        if not os.path.exists(dark_qss_path):
            logger.warning(f"样式表文件未找到: {dark_qss_path}")
            return ""
            
        try:
            with open(dark_qss_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            # 自动将 QSS 中的相对图片路径转换为基于 resource_path 的绝对路径
            def replace_url(match):
                raw = match.group(1).strip("\"'")
                parts = raw.replace('\\', '/').split('/')
                if parts[0] == 'app':
                    parts = parts[1:]
                abs_p = resource_path(*parts).replace('\\', '/')
                return f'url("{abs_p}")'
                
            pattern = re.compile(r'url\((?!["\']?(?:http|file|data):)["\']?([^)"\']+)["\']?\)')
            return pattern.sub(replace_url, content)
        except Exception as e:
            logger.error(f"加载样式表失败: {e}")
            return ""

    @staticmethod
    def apply_theme(theme_name: str = None):
        """应用默认深色主题"""
        app = QApplication.instance()
        if not app:
            return
            
        stylesheet = ThemeManager.load_stylesheet()
        if stylesheet:
            app.setStyleSheet(stylesheet)
            logger.info("已加载并应用深色机甲主题样式表 (#212123)")

    # 兼容历史调用接口
    @staticmethod
    def apply_system_theme(*args, **kwargs):
        ThemeManager.apply_theme()

    @staticmethod
    def setup_system_theme_listener():
        pass
