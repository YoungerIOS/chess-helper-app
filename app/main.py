import sys
import traceback
import os
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QLoggingCategory

# Ensure bundled app can import packages
if getattr(sys, 'frozen', False):
    macos_dir = os.path.dirname(sys.executable)  # .../Contents/MacOS
    resources_dir = os.path.abspath(os.path.join(macos_dir, '..', 'Resources'))
    frameworks_dir = os.path.abspath(os.path.join(macos_dir, '..', 'Frameworks'))
    resources_app_dir = os.path.join(resources_dir, 'app')
    frameworks_app_dir = os.path.join(frameworks_dir, 'app')
    for p in [resources_dir, frameworks_dir, resources_app_dir, frameworks_app_dir]:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
else:
    # 开发环境：确保项目根目录在 sys.path 中
    current_file_dir = os.path.abspath(os.path.dirname(__file__))  # app/ 目录
    project_root = os.path.dirname(current_file_dir)  # 项目根目录
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from app.chess.context import logger
from app.ui.main_window import MainWindow

# 禁用ICC相关的警告
QLoggingCategory.setFilterRules("qt.gui.icc.warning=false")

def _ensure_engine_files():
    """静默确保引擎文件存在于用户数据目录中"""
    try:
        from app.tools.utils import app_data_path, resource_path
        import shutil
        
        # 检查用户数据目录中的引擎文件
        user_engine_path = app_data_path("Pikafish/pikafish")
        user_nnue_path = app_data_path("Pikafish/pikafish.nnue")
        
        # 如果引擎文件不存在，尝试从打包资源复制
        if not os.path.exists(user_engine_path):
            src_engine = resource_path("Pikafish", "src", "pikafish")
            if os.path.exists(src_engine):
                # 确保目标目录存在
                os.makedirs(os.path.dirname(user_engine_path), exist_ok=True)
                # 复制引擎文件
                shutil.copy2(src_engine, user_engine_path)
                # 设置执行权限
                os.chmod(user_engine_path, 0o755)
                logger.info("引擎文件已静默复制到用户数据目录")
        
        # 如果NNUE文件不存在，尝试从打包资源复制
        if not os.path.exists(user_nnue_path):
            src_nnue = resource_path("Pikafish", "src", "pikafish.nnue")
            if os.path.exists(src_nnue):
                # 确保目标目录存在
                os.makedirs(os.path.dirname(user_nnue_path), exist_ok=True)
                # 复制NNUE文件
                shutil.copy2(src_nnue, user_nnue_path)
                logger.info("NNUE文件已静默复制到用户数据目录")
                
    except Exception as e:
        # 静默处理错误，不影响应用启动
        logger.debug(f"引擎文件复制失败（不影响应用启动）: {e}")
        pass

def excepthook(exctype, value, tb):
    # 写日志
    try:
        logger.error("Uncaught exception:", exc_info=(exctype, value, tb))
    except Exception:
        pass
    # 弹消息框，便于双击启动时看到错误
    try:
        msg = "\n".join(traceback.format_exception(exctype, value, tb)[-3:])
        m = QMessageBox()
        m.setWindowTitle("程序异常退出")
        m.setText("发生未捕获异常，程序将退出。\n" + msg)
        m.setIcon(QMessageBox.Critical)
        m.exec()
    except Exception:
        pass
    # 退出
    sys.__excepthook__(exctype, value, tb)


def main():
    sys.excepthook = excepthook
    
    # 复制引擎文件到用户目录（如果不存在）
    _ensure_engine_files()
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

# 这个if是判断当前脚本文件是否为独立直接运行的,如果是,则条件通过, 
# 如果是作为模块导入到其他文件后运行到这里的,则条件不通过.  
if __name__ == "__main__":  
    main()