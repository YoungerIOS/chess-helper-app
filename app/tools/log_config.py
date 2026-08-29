"""项目统一日志入口。

所有模块都使用 Python logging 的 ``chess`` logger 层级，避免
logging、Loguru 和 print 产生三种不同的终端格式。具体的终端/
文件 handler 由 ``app.chess.context.setup_logging`` 根据用户配置安装。
"""

import logging


def get_logger(name: str = None) -> logging.Logger:
    """返回 chess 层级下的标准 logger。"""
    if not name or name == "chess":
        return logging.getLogger("chess")
    if name.startswith("chess."):
        logger_name = name
    else:
        short_name = name
        for prefix in ("app.chess.", "app.ui.", "app.themes.", "app.tools.", "app."):
            if short_name.startswith(prefix):
                short_name = short_name[len(prefix):]
                break
        logger_name = f"chess.{short_name}"
    return logging.getLogger(logger_name)


def setup_file_logging(log_dir="logs"):
    """保留旧API；文件日志现由 context 的统一配置管理。"""
    return get_logger()


logger = get_logger()

__all__ = ["logger", "get_logger", "setup_file_logging"]
