from dataclasses import dataclass, field
from typing import Dict, Optional, List
from tools import utils
import json

@dataclass
class Platform:
    """平台配置类，包含平台相关的所有信息"""
    name: str                    # 平台名称，如 'TT'、'JJ'
    template_path: str           # 模板图片目录
    board_coords: Dict[str, List[int]] = field(default_factory=lambda: {"x": [], "y": []})  # 棋盘坐标
    regions: Dict = field(default_factory=lambda: {
        "board": {"left": 0, "top": 0, "width": 375, "height": 415},
        "avatar": {"left": 0, "top": 0, "width": 93.75, "height": 124.5}
    })  # 区域配置
    
    def __post_init__(self):
        """初始化时设置模板路径"""
        self.template_path = utils.resource_path(f"images/{self.name.lower()}")

@dataclass
class ChessContext:
    """象棋助手上下文对象，包含所有共享状态"""
    platform: str                    # 当前平台
    template_path: str              # 模板路径
    engine_params: Dict = field(default_factory=dict)  # 引擎参数
    is_red: bool = False           # 是否红方
    is_running: bool = False       # 是否正在运行
    piece_recognizer: Optional[object] = None  # 添加棋子识别器属性
    
    def __post_init__(self):
        """初始化时加载配置"""
        self.load_config()
    
    def load_config(self):
        """从配置文件加载所有设置"""
        try:
            with open(utils.resource_path("json/platform_config.json"), "r") as f:
                config = json.load(f)
                
            # 初始化平台
            self._platforms = {}
            for platform_name, platform_config in config.items():
                if platform_name in ['TT', 'JJ']:
                    self._platforms[platform_name] = Platform(
                        name=platform_name,
                        template_path=utils.resource_path(f"images/{platform_name.lower()}"),
                        board_coords=platform_config['board_coords'],
                        regions=platform_config['regions']
                    )
            
            # 加载引擎参数
            self.engine_params = config.get('engine_params', {
                "movetime": "3000",
                "depth": "20",
                "goParam": "depth"
            })
            
            # 设置当前平台
            self.platform = config.get('platform', 'TT')
            self.template_path = self._platforms[self.platform].template_path
            
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading config: {e}")
            # 使用默认值初始化
            self._platforms = {
                'TT': Platform(name='TT', template_path=utils.resource_path("images/tiantian")),
                'JJ': Platform(name='JJ', template_path=utils.resource_path("images/jj"))
            }
            self.engine_params = {
                "movetime": "3000",
                "depth": "20",
                "goParam": "depth"
            }
            self.platform = "TT"
            self.template_path = self._platforms["TT"].template_path
    
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
            config['engine_params'] = self.engine_params
            
            with open(utils.resource_path("json/platform_config.json"), "w") as f:
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
        self.template_path = platform.template_path
        
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

# 创建全局上下文实例
context = ChessContext(
    platform="TT",
    template_path="",
    engine_params={}
) 