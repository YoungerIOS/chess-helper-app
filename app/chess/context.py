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
    
    def __post_init__(self):
        """初始化时设置模板路径"""
        self.template_path = utils.resource_path(f"images/{self.platform.lower()}")
        self._platforms = {
            'TT': Platform(
                name='TT',
                template_path=utils.resource_path("images/tiantian"),
                board_coords={"x": [], "y": []}
            ),
            'JJ': Platform(
                name='JJ',
                template_path=utils.resource_path("images/jj"),
                board_coords={"x": [], "y": []}
            )
        }
        # 加载棋盘坐标
        self.load_board_coords()
    
    def set_platform(self, platform_name: str) -> None:
        """设置当前平台"""
        if platform_name not in self._platforms:
            raise ValueError(f"未知的平台: {platform_name}")
        
        # 获取目标平台
        platform = self._platforms[platform_name]
        
        # 更新当前平台信息
        self.platform = platform_name
        self.template_path = platform.template_path
        
        # 确保坐标数组已初始化
        if not platform.board_coords["x"] or not platform.board_coords["y"]:
            platform.board_coords = {"x": [], "y": []}
        
        # 保存更新后的坐标
        self.save_board_coords()
    
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
    
    def load_board_coords(self) -> None:
        """从文件加载棋盘坐标"""
        try:
            with open(utils.resource_path("json/board.json"), "r") as f:
                data = json.load(f)
                for platform_name, coords in data.items():
                    if platform_name in self._platforms:
                        self._platforms[platform_name].board_coords = coords
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading board coordinates: {e}")
    
    def save_board_coords(self) -> None:
        """保存棋盘坐标到文件"""
        try:
            data = {
                platform_name: platform.board_coords
                for platform_name, platform in self._platforms.items()
            }
            with open(utils.resource_path("json/board.json"), "w") as f:
                json_str = json.dumps(data, indent=4)
                f.write(json_str)
        except Exception as e:
            print(f"Error saving board coordinates: {e}")

# 创建全局上下文实例
context = ChessContext(
    platform="TT",
    template_path="",
    engine_params={}
) 