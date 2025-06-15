from dataclasses import dataclass, field
from typing import Dict, Optional, List
from tools.utils import resource_path
import json
from threading import Lock

@dataclass
class Platform:
    """平台配置类，包含平台相关的所有信息"""
    name: str                    # 平台名称，如 'TT'、'JJ'
    board_coords: Dict[str, List[int]]  # 棋盘坐标
    regions: Dict  # 区域配置
    _piece_recognizer: Optional[object] = None  # 棋子识别器
    _timer_recognizer: Optional[object] = None  # 倒计时识别器
    animation_delay: float = 0.3  # 动画等待时长（秒）
    
    def __post_init__(self):
        """初始化时设置动画等待时长"""
        # 根据平台设置不同的动画等待时长
        self.animation_delay = 1.2 if self.name == 'TT' else 0.3
    
    @property
    def piece_recognizer(self) -> object:
        """获取棋子识别器"""
        if self._piece_recognizer is None:
            from chess.piece_recognizer import ChessPieceRecognizer
            self._piece_recognizer = ChessPieceRecognizer(platform=self.name)
        return self._piece_recognizer
    
    @property
    def timer_recognizer(self) -> object:
        """获取倒计时识别器"""
        if self._timer_recognizer is None:
            from chess.timer_recognizer import CountdownPredictor
            self._timer_recognizer = CountdownPredictor(platform=self.name)
        return self._timer_recognizer

@dataclass
class ChessContext:
    """象棋助手上下文对象，包含所有共享状态"""
    platform: str                    # 当前平台
    _engine_params: Dict[str, str] = field(default_factory=dict)
    _engine_params_lock: Lock = field(default_factory=Lock)
    _platforms: Dict[str, Platform] = field(default_factory=dict)
    _analysis_mode: str = field(default="timer")  # 使用 field 确保默认值在实例化时设置
    position_checker: Optional[object] = None  # 局面检查器

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
            with open(resource_path("json/platform_config.json"), "r") as f:
                config = json.load(f)
                
            # 初始化平台
            self._platforms = {}
            for platform_name, platform_config in config.items():
                if platform_name in ['TT', 'JJ']:
                    self._platforms[platform_name] = Platform(
                        name=platform_name,
                        board_coords=platform_config['board_coords'],
                        regions=platform_config['regions']
                    )
            
            # 加载引擎参数
            with self._engine_params_lock:
                self._engine_params = config.get('engine_params', {
                    "movetime": "3000",
                    "depth": "20",
                    "goParam": "depth"
                }).copy()
            
            # 设置当前平台
            self.platform = config.get('platform', 'TT')
            
            # 设置分析模式
            self._analysis_mode = config.get('analysis_mode', 'timer')
            
            # 预加载当前平台的模型
            _ = self.piece_recognizer
            _ = self.timer_recognizer
            print("模型初始化完成")
            
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading config: {e}")
            # 使用默认值初始化
            self._platforms = {
                'TT': Platform(name='TT'),
                'JJ': Platform(name='JJ')
            }
            with self._engine_params_lock:
                self._engine_params = {
                    "movetime": "3000",
                    "depth": "20",
                    "goParam": "depth"
                }.copy()
            self.platform = "TT"
            self._analysis_mode = "timer"
            
            # 预加载默认平台的模型
            _ = self.piece_recognizer
            _ = self.timer_recognizer
            print("模型初始化完成")
    
    def save_config(self):
        """保存所有配置到文件"""
        try:
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
            
            # 获取引擎参数的副本
            with self._engine_params_lock:
                config['engine_params'] = self._engine_params.copy()
            
            with open(resource_path("json/platform_config.json"), "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def set_platform(self, platform_name: str) -> None:
        """设置当前平台"""
        if platform_name not in self._platforms:
            raise ValueError(f"未知的平台: {platform_name}")
        
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
    def timer_recognizer(self) -> object:
        """获取当前平台的倒计时识别器"""
        return self._platforms[self.platform].timer_recognizer

    @property
    def animation_delay(self) -> float:
        """获取当前平台的动画等待时长"""
        return self._platforms[self.platform].animation_delay

    @property
    def analysis_mode(self) -> str:
        return self._analysis_mode

    @analysis_mode.setter
    def analysis_mode(self, mode: str):
        self._analysis_mode = mode
        self.save_config()  # 保存配置

    def init_position_checker(self):
        """初始化局面检查器"""
        from .checker import PositionChecker
        self.position_checker = PositionChecker()

    def clear_position_checker(self):
        """清理局面检查器"""
        self.position_checker = None

# 创建全局上下文实例
context = ChessContext(platform="TT")  # 默认使用TT平台 