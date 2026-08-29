import os
from PySide6.QtWidgets import QApplication
from app.chess.context import context
from app.tools.log_config import get_logger


logger = get_logger(__name__)

class ThemeManager:
    """主题管理器"""
    
    THEME_DARK = "dark"
    THEME_LIGHT = "light"
    
    @staticmethod
    def get_theme_path(theme_name):
        """获取主题文件的绝对路径"""
        # 假设主题文件位于当前文件的同级目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(current_dir, f"{theme_name}.qss")
    
    @staticmethod
    def load_stylesheet(theme_name):
        """加载 QSS 样式表内容"""
        path = ThemeManager.get_theme_path(theme_name)
        if not os.path.exists(path):
            logger.warning(f"未找到主题文件: {path}")
            return ""
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            logger.exception(f"加载主题失败: {theme_name}")
            return ""
            
    @staticmethod
    def apply_theme(theme_name):
        """应用主题"""
        app = QApplication.instance()
        if not app:
            return
            
        stylesheet = ThemeManager.load_stylesheet(theme_name)
        if stylesheet:
            app.setStyleSheet(stylesheet)
            # 保存当前主题设置
            context.theme = theme_name
            context.save_config()
            logger.info(f"已应用主题: {theme_name}")

    @staticmethod
    def toggle_theme():
        """切换主题"""
        current_theme = getattr(context, 'theme', ThemeManager.THEME_LIGHT)
        new_theme = ThemeManager.THEME_DARK if current_theme == ThemeManager.THEME_LIGHT else ThemeManager.THEME_LIGHT
        ThemeManager.apply_theme(new_theme)
        return new_theme
