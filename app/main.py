import os
import sys
import traceback


def _enable_windows_dpi_awareness():
    """Keep Win32, MSS and mouse coordinates in physical-pixel space."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        # Per-monitor v2; available on current Windows 10/11 releases.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


# 这必须在导入Qt或创建MSS捕获实例之前进行。
_enable_windows_dpi_awareness()


# Ensure bundled app can import packages
if getattr(sys, "frozen", False):
    macos_dir = os.path.dirname(sys.executable)  # .../Contents/MacOS
    resources_dir = os.path.abspath(os.path.join(macos_dir, "..", "Resources"))
    frameworks_dir = os.path.abspath(os.path.join(macos_dir, "..", "Frameworks"))
    resources_app_dir = os.path.join(resources_dir, "app")
    frameworks_app_dir = os.path.join(frameworks_dir, "app")
    for p in [resources_dir, frameworks_dir, resources_app_dir, frameworks_app_dir]:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
else:
    # 开发环境：确保项目根目录在 sys.path 中
    current_file_dir = os.path.abspath(os.path.dirname(__file__))  # app/ 目录
    project_root = os.path.dirname(current_file_dir)  # 项目根目录
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


from PySide6.QtWidgets import QApplication, QMessageBox

from app.chess.context import logger
from app.ui.main_window import MainWindow

# 禁用ICC相关的警告
# QLoggingCategory.setFilterRules("qt.gui.icc.warning=false")


def _ensure_engine_files():
    """静默确保引擎文件存在于项目引擎文件夹中"""
    try:
        import shutil

        from app.tools.utils import engine_path, get_engine_dir, resource_path

        engine_dir = get_engine_dir()
        target_engine_path = engine_path("pikafish")
        target_nnue_path = engine_path("pikafish.nnue")

        # 如果引擎文件不存在，尝试从打包资源复制；源和目标是同一文件时跳过
        if not os.path.exists(target_engine_path):
            for src_engine in (
                resource_path("Pikafish", "src", "pikafish"),
                resource_path("Pikafish", "pikafish"),
            ):
                if os.path.exists(src_engine) and os.path.abspath(
                    src_engine
                ) != os.path.abspath(target_engine_path):
                    shutil.copy2(src_engine, target_engine_path)
                    logger.info(f"引擎文件已静默复制到 {engine_dir}")
                    break

            # 确保有执行权限
            if os.path.exists(target_engine_path):
                os.chmod(target_engine_path, 0o755)

        # 如果NNUE文件不存在，尝试从打包资源复制
        if not os.path.exists(target_nnue_path):
            for src_nnue in (
                resource_path("Pikafish", "src", "pikafish.nnue"),
                resource_path("Pikafish", "pikafish.nnue"),
            ):
                if os.path.exists(src_nnue) and os.path.abspath(
                    src_nnue
                ) != os.path.abspath(target_nnue_path):
                    shutil.copy2(src_nnue, target_nnue_path)
                    logger.info(f"NNUE文件已静默复制到 {engine_dir}")

    except Exception as e:  # noqa: BLE001
        # 静默处理错误，不影响应用启动
        logger.debug(f"引擎文件复制失败（不影响应用启动）: {e}")


def check_screen_recording_permission():
    """
    检查屏幕录制权限。

    使用 CoreGraphics 的权限 API，避免在应用启动阶段同步创建截图后端并
    抓取像素；后者在显示器较多或系统截图服务繁忙时会明显拖慢启动。
    """
    if sys.platform != "darwin":
        return

    try:
        import Quartz

        # PyObjC 会在运行时动态导出这两个 CoreGraphics API，但其类型桩
        # 不一定声明它们。动态获取既避免 Pylance 误报，也兼容缺少该
        # API 的旧系统；不要用整行 type: ignore 掩盖其他属性错误。
        preflight_access = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
        request_access = getattr(Quartz, "CGRequestScreenCaptureAccess", None)
        if not callable(preflight_access) or not callable(request_access):
            logger.warning("当前系统不提供屏幕录制权限检查 API")
            return

        if preflight_access():
            logger.info("屏幕录制权限检查: 已授权")
            return

        if request_access():
            logger.info("屏幕录制权限检查: 已授权")
        else:
            logger.warning("屏幕录制权限尚未授权，请在系统设置中允许本应用录制屏幕")
    except (ImportError, AttributeError, OSError, TypeError) as e:
        logger.warning(f"无法读取屏幕录制权限状态: {e}")


def excepthook(exctype, value, tb):
    # 写日志
    try:
        logger.error("Uncaught exception:", exc_info=(exctype, value, tb))
    except (AttributeError, OSError, RuntimeError, TypeError) as exc:
        logger.exception("显示异常消息框失败: %s", exc)
    # 弹消息框，便于双击启动时看到错误
    try:
        msg = "\n".join(traceback.format_exception(exctype, value, tb)[-3:])
        m = QMessageBox()
        m.setWindowTitle("程序异常退出")
        m.setText("发生未捕获异常，程序将退出。\n" + msg)
        m.setIcon(QMessageBox.Icon.Critical)
        m.exec()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.exception("显示异常消息框失败: %s", exc)
    # 退出
    sys.__excepthook__(exctype, value, tb)


def main():
    sys.excepthook = excepthook

    # 复制引擎文件到用户目录（如果不存在）
    _ensure_engine_files()

    # 尽早触发屏幕录制权限申请
    check_screen_recording_permission()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
