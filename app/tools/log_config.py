"""
统一日志配置模块
基于 loguru 提供项目级别的日志管理
"""
import sys
import os
from loguru import logger

# 移除默认的 handler
logger.remove()

# 允许显示日志的模块列表（可根据需要修改）
ENABLED_MODULES = [
    "app.chess.checker",
    "app.chess.processor", 
    "app.chess.auto_mover",
    # "app.chess.recognizer",
]

def _module_filter(record):
    """过滤器：只允许指定模块的日志"""
    name = record["extra"].get("name", "")
    return any(module in name for module in ENABLED_MODULES)

# 控制台输出配置
logger.add(
    sys.stderr,
    level="DEBUG",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[name]}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    filter=_module_filter,
    colorize=True
)

# 文件输出配置（可选，按日期轮转）
def setup_file_logging(log_dir="logs"):
    """设置文件日志（可选调用）"""
    os.makedirs(log_dir, exist_ok=True)
    logger.add(
        os.path.join(log_dir, "chess_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="00:00",  # 每天午夜轮转
        retention="7 days",  # 保留7天
        encoding="utf-8"
    )

def get_logger(name: str = None):
    """
    获取带模块名的 logger
    
    Usage:
        from app.tools.log_config import get_logger
        logger = get_logger(__name__)
        logger.debug("调试信息")
    """
    if name:
        return logger.bind(name=name)
    return logger

# 导出
__all__ = ["logger", "get_logger", "setup_file_logging"]
