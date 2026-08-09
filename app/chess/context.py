import json
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from datetime import datetime
from threading import Lock
from app.tools import utils
from app.chess.history import MoveHistory 

def setup_logging():
    """初始化日志系统"""
    # 检查是否已经初始化过
    if hasattr(setup_logging, '_initialized'):
        return logging.getLogger('chess')
    
    # 创建日志目录
    log_dir = os.path.expanduser("~/Library/Logs/chess-helper-app")
    os.makedirs(log_dir, exist_ok=True)
    
    # 读取日志配置
    log_config = {
        "log_level": "INFO",
        "log_to_file": True,
        "log_to_console": True,
        "max_log_size_mb": 10,
        "backup_count": 5,
        "log_format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "date_format": "%Y-%m-%d %H:%M:%S"
    }
    
    try:
        log_config_path = utils.resource_path("json", "log_config.json")
        if os.path.exists(log_config_path):
            with open(log_config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                log_config.update(user_config)
    except Exception:
        pass  # 使用默认配置
    
    # 生成日志文件名
    log_file = os.path.join(log_dir, f"chess_helper_{datetime.now().strftime('%Y%m%d')}.log")
    
    # 创建chess模块的日志记录器
    chess_logger = logging.getLogger('chess')
    chess_logger.setLevel(getattr(logging, log_config["log_level"].upper(), logging.INFO))
    
    # 清除现有处理器
    chess_logger.handlers.clear()
    
    # 添加文件处理器
    if log_config["log_to_file"]:
        from logging.handlers import RotatingFileHandler
        max_bytes = log_config["max_log_size_mb"] * 1024 * 1024
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=max_bytes, 
            backupCount=log_config["backup_count"],
            encoding='utf-8'
        )
        file_handler.setFormatter(logging.Formatter(log_config["log_format"], log_config["date_format"]))
        chess_logger.addHandler(file_handler)
    
    # 添加控制台处理器
    if log_config["log_to_console"]:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_config["log_format"], log_config["date_format"]))
        chess_logger.addHandler(console_handler)
    
    # 标记为已初始化
    setup_logging._initialized = True
    
    return chess_logger

# 初始化日志系统
logger = setup_logging()

DEFAULT_ENGINE_PARAMS = {
    "movetime": "2000",
    "depth": "25",
    "goParam": "movetime",
    "threads": "8",
    "hash": "256",
    "settings_version": "2",
}

@dataclass
class Platform:
    """平台配置类，包含平台相关的所有信息"""
    name: str                    # 平台名称，如 'TT'、'JJ'
    board_coords: Dict[str, List[int]]  # 棋盘坐标
    regions: Dict  # 区域配置
    _piece_recognizer: Optional[object] = None  # 棋子识别器

    
    def __post_init__(self):
        """初始化时设置动画等待时长"""
        pass
    
    @property
    def piece_recognizer(self) -> object:
        """获取棋子识别器"""
        if self._piece_recognizer is None:
            from app.chess.piece_recognizer import ChessPieceRecognizer
            self._piece_recognizer = ChessPieceRecognizer(platform=self.name)
        return self._piece_recognizer
    


@dataclass
class ChessContext:
    """象棋助手上下文对象，包含所有共享状态"""
    platform: str                    # 当前平台
    _engine_params: Dict[str, str] = field(default_factory=dict)
    _engine_params_lock: Lock = field(default_factory=Lock)
    _platforms: Dict[str, Platform] = field(default_factory=dict)
    _analysis_mode: str = field(default="timer")  
    engine: Optional[object] = None  # 当前引擎实例
    _engine_lock: Lock = field(default_factory=Lock)  # 引擎访问锁
    checker: Optional[object] = None  # 局面检查器
    _checker_lock: Lock = field(default_factory=Lock)  # 检查器访问锁
    recognizer: Optional[object] = None  # 棋盘识别器(High Level)
    _recognizer_lock: Lock = field(default_factory=Lock) # 识别器访问锁
    history: MoveHistory = field(default_factory=MoveHistory)
    screen_size: Optional[tuple] = None  # 屏幕尺寸
    _board_index: int = 0  # 棋盘皮肤索引（私有存储）
    _manual_coords: Optional[tuple] = None  # 手动定位坐标 (x, y, width, height)
    base_fen: Optional[str] = None # 用于历史中断时的锚点FEN (持久化存储)
    analysis_token: int = 0  # 引擎分析令牌，用于废弃过期的回调
    _analysis_token_lock: Lock = field(default_factory=Lock)
    discard_before_timestamp: float = 0.0  # RETRY时设置，过滤在此时间之前截图的帧
    _theme: str = "light"  # 当前主题
    _auto_move_enabled: bool = False  # 自动走子默认关闭
    _capture_depth_enabled: bool = False  # 我方被吃子时动态增加搜索深度
    _game_variant: str = "xiangqi"  # xiangqi（普通象棋）/ jieqi（揭棋）
    
    
    def __post_init__(self):
        """初始化时加载配置"""
        self.load_config()
    
    def get_engine_params(self) -> Dict:
        """线程安全地获取引擎参数"""
        with self._engine_params_lock:
            return self._engine_params.copy()  # 返回副本避免外部修改

    def update_engine_params(self, new_params: Dict) -> None:
        """线程安全地更新引擎参数"""
        with self._engine_params_lock:
            self._engine_params = new_params.copy()  # 存储副本避免外部修改
        
        # 在锁外保存配置
        self.save_config()

    def load_config(self):
        """从配置文件加载所有设置"""
        try:
            logger.info("开始加载配置文件...")
            with open(utils.resource_path("json", "game_config.json"), "r") as f:
                config = json.load(f)
                
            # 初始化平台
            self._platforms = {}
            for platform_name, game_config in config.items():
                if platform_name in ['TT', 'JJ']:
                    self._platforms[platform_name] = Platform(
                        name=platform_name,
                        board_coords=game_config['board_coords'],
                        regions=game_config['regions']
                    )
            
            # 加载引擎参数
            with self._engine_params_lock:
                # 合并默认值，让旧配置自动获得新增的 threads/hash 参数。
                saved_engine_params = config.get('engine_params', {})
                if saved_engine_params.get("settings_version") != "2":
                    # v2新增线程调节控件，并采用本机实测后的平衡配置。
                    saved_engine_params = {
                        **saved_engine_params,
                        "movetime": "2000",
                        "goParam": "movetime",
                        "threads": "8",
                        "settings_version": "2",
                    }
                self._engine_params = {
                    **DEFAULT_ENGINE_PARAMS,
                    **saved_engine_params
                }
            
            # 设置当前平台
            self.platform = config.get('platform', 'TT')
            logger.info(f"当前平台设置为: {self.platform}")
            
            # 设置分析模式
            self._analysis_mode = config.get('analysis_mode', 'timer')
            logger.info(f"分析模式设置为: {self._analysis_mode}")

            self._auto_move_enabled = bool(config.get('auto_move_enabled', False))
            logger.info(f"自动走子设置为: {self._auto_move_enabled}")
            self._capture_depth_enabled = bool(config.get('capture_depth_enabled', False))
            logger.info(f"被吃子加深设置为: {self._capture_depth_enabled}")
            self._game_variant = config.get('game_variant', 'xiangqi')
            if self._game_variant not in ('xiangqi', 'jieqi'):
                self._game_variant = 'xiangqi'
            logger.info(f"棋类模式设置为: {self._game_variant}")
            
            # 读取棋盘底图索引（直接设置私有字段，避免加载时触发保存）
            self._board_index = config.get('board_index', 0)
            # 读取棋盘底图索引（直接设置私有字段，避免加载时触发保存）
            self._board_index = config.get('board_index', 0)
            logger.info(f"棋盘皮肤索引设置为: {self._board_index}")
            
            # 读取主题
            self._theme = config.get('theme', 'light')
            logger.info(f"主题设置为: {self._theme}")
            
            # 预加载当前平台的模型
            _ = self.piece_recognizer

            logger.info("模型初始化完成")
            
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Error loading config: {e}")
            # 使用默认值初始化
            self._platforms = {
                'TT': Platform(
                    name='TT',
                    board_coords={'x': [], 'y': []},
                    regions={}
                ),
                'JJ': Platform(
                    name='JJ',
                    board_coords={'x': [], 'y': []},
                    regions={}
                )
            }
            with self._engine_params_lock:
                self._engine_params = DEFAULT_ENGINE_PARAMS.copy()
            self.platform = "TT"
            self._analysis_mode = "timer"
            self._auto_move_enabled = False
            self._capture_depth_enabled = False
            self._game_variant = "xiangqi"
            
            # 预加载默认平台的模型
            _ = self.piece_recognizer

            logger.info("模型初始化完成")
    
    def save_config(self):
        """保存所有配置到文件"""
        try:
            logger.info("开始保存配置文件...")
            # 先创建平台配置
            config = {
                platform_name: {
                    'board_coords': platform.board_coords,
                    'regions': platform.regions
                }
                for platform_name, platform in self._platforms.items()
            }
            # 添加其他配置
            config['platform'] = self.platform
            config['analysis_mode'] = self._analysis_mode
            config['auto_move_enabled'] = self._auto_move_enabled
            config['capture_depth_enabled'] = self._capture_depth_enabled
            config['game_variant'] = self._game_variant
    
            # 保存棋盘底图索引
            config['board_index'] = self.board_index
            # 保存主题
            config['theme'] = self._theme
            
            # 获取引擎参数的副本
            with self._engine_params_lock:
                config['engine_params'] = self._engine_params.copy()
            
            # 递归转换所有numpy类型
            config = utils.convert_to_builtin_type(config)
            
            # 使用原子写入避免文件损坏
            path = utils.resource_path("json", "game_config.json")
            tmp_path = path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(config, f, indent=4)
            os.replace(tmp_path, path)  # 原子覆盖
            logger.info("配置文件保存成功")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    def set_platform(self, platform_name: str) -> None:
        """设置当前平台"""
        if platform_name not in self._platforms:
            error_msg = f"未知的平台: {platform_name}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # 获取目标平台
        platform = self._platforms[platform_name]
        
        # 更新当前平台信息
        self.platform = platform_name
        
        # 保存配置
        self.save_config()
    
    def get_platform(self, platform_name: str) -> Platform:
        """获取指定平台"""
        if platform_name not in self._platforms:
            raise ValueError(f"未知的平台: {platform_name}")
        return self._platforms[platform_name]
    
    @property
    def board_coords(self) -> Dict[str, List[int]]:
        """获取当前平台的棋盘坐标"""
        return self._platforms[self.platform].board_coords
    
    @board_coords.setter
    def board_coords(self, coords: Dict[str, List[int]]) -> None:
        """设置当前平台的棋盘坐标"""
        self._platforms[self.platform].board_coords = coords
        self.save_config()
    
    @property
    def regions(self) -> Dict:
        """获取当前平台的区域配置"""
        return self._platforms[self.platform].regions
    
    @regions.setter
    def regions(self, regions: Dict) -> None:
        """设置当前平台的区域配置"""
        self._platforms[self.platform].regions = regions
        self.save_config()

    @property
    def piece_recognizer(self) -> object:
        """获取当前平台的棋子识别器"""
        return self._platforms[self.platform].piece_recognizer
    
    @property
    def analysis_mode(self) -> str:
        return self._analysis_mode

    @analysis_mode.setter
    def analysis_mode(self, mode: str):
        self._analysis_mode = mode
        self.save_config()  # 保存配置

    @property
    def auto_move_enabled(self) -> bool:
        return self._auto_move_enabled

    @auto_move_enabled.setter
    def auto_move_enabled(self, enabled: bool) -> None:
        self._auto_move_enabled = bool(enabled)
        self.save_config()

    @property
    def capture_depth_enabled(self) -> bool:
        return self._capture_depth_enabled

    @capture_depth_enabled.setter
    def capture_depth_enabled(self, enabled: bool) -> None:
        self._capture_depth_enabled = bool(enabled)
        self.save_config()

    @property
    def game_variant(self) -> str:
        return self._game_variant

    @game_variant.setter
    def game_variant(self, variant: str) -> None:
        if variant not in ('xiangqi', 'jieqi'):
            raise ValueError(f"未知棋类模式: {variant}")
        self._game_variant = variant
        self.save_config()

    def next_analysis_token(self) -> int:
        with self._analysis_token_lock:
            self.analysis_token += 1
            return self.analysis_token

    def invalidate_analysis(self) -> int:
        return self.next_analysis_token()

    def is_analysis_token_current(self, token: int) -> bool:
        with self._analysis_token_lock:
            return token == self.analysis_token
    

    
    def get_log_info(self) -> dict:
        """获取日志系统信息"""
        try:
            from app.tools.log_viewer import LogViewer
            viewer = LogViewer()
            log_files = viewer.get_log_files()
            
            if log_files:
                latest_log = log_files[0]
                stats = viewer.get_log_stats(latest_log)
                return {
                    "log_files_count": len(log_files),
                    "latest_log": os.path.basename(latest_log),
                    "latest_log_stats": stats
                }
            else:
                return {"log_files_count": 0, "latest_log": None, "latest_log_stats": None}
        except Exception as e:
            logger.error(f"获取日志信息失败: {e}")
            return {"error": str(e)}
    
    @property
    def board_index(self) -> int:
        """获取棋盘皮肤索引"""
        return self._board_index

    @board_index.setter
    def board_index(self, value: int) -> None:
        """设置棋盘皮肤索引并持久化"""
        self._board_index = int(value)
        self.save_config()

    @property
    def manual_coords(self) -> Optional[tuple]:
        """获取手动定位坐标"""
        return self._manual_coords

    @manual_coords.setter
    def manual_coords(self, coords: Optional[tuple]) -> None:
        """设置手动定位坐标"""
        self._manual_coords = coords

    def get_checker(self) -> Optional[object]:
        """线程安全地获取检查器"""
        with self._checker_lock:
            return self.checker

    def set_checker(self, checker: Optional[object]) -> None:
        """线程安全地设置检查器"""
        with self._checker_lock:
            self.checker = checker

    def reset_checker(self) -> None:
        """线程安全地重置检查器状态"""
        with self._checker_lock:
            if self.checker:
                self.checker.reset()

    def get_recognizer(self) -> Optional[object]:
        """线程安全地获取识别器"""
        with self._recognizer_lock:
            return self.recognizer

    def set_recognizer(self, recognizer: Optional[object]) -> None:
        """线程安全地设置识别器"""
        with self._recognizer_lock:
            self.recognizer = recognizer
    
    def reset_recognizer(self) -> None:
        """线程安全地重置识别器状态"""
        with self._recognizer_lock:
            if self.recognizer and hasattr(self.recognizer, 'reset'):
                self.recognizer.reset()

    def get_engine(self) -> Optional[object]:
        """线程安全地获取引擎"""
        with self._engine_lock:
            return self.engine

    def set_engine(self, engine: Optional[object]) -> None:
        """线程安全地设置引擎"""
        with self._engine_lock:
            self.engine = engine

    def quit_engine(self, fast: bool = False) -> None:
        """线程安全地完全退出引擎"""
        with self._engine_lock:
            if self.engine:
                self.engine.quit(fast=fast)
                self.engine = None
    
    @property
    def theme(self) -> str:
        """获取当前主题"""
        return self._theme

    @theme.setter
    def theme(self, value: str) -> None:
        """设置当前主题"""
        self._theme = value
        self.save_config()


# 创建全局上下文实例
_context_instance = None

def get_context():
    """获取全局上下文实例（单例模式）"""
    global _context_instance
    if _context_instance is None:
        _context_instance = ChessContext(platform="TT")  # 默认使用TT平台
    return _context_instance

# 为了向后兼容，保留context变量
context = get_context()
