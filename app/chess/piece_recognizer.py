import torch
import torch.nn as nn
from torchvision import models, transforms
from torchvision.models import MobileNet_V2_Weights
from PIL import Image
import json
import os

class ChessPieceRecognizer:
    def __init__(self, model_path="model.pth", class_map_path="class_map.json"):
        """
        初始化棋子识别器
        :param model_path: 模型文件路径
        :param class_map_path: 类别映射文件路径
        """
        # 检测设备
        self.device = (
            torch.device("mps") if torch.backends.mps.is_available()
            else torch.device("cuda" if torch.cuda.is_available() else "cpu")
        )
        
        # 图像预处理
        self.transform = transforms.Compose([
            transforms.Resize((80, 80)),
            transforms.ToTensor(),
        ])
        
        # 加载类别映射
        with open(class_map_path, "r", encoding="utf-8") as f:
            self.class_map = json.load(f)
        
        # 加载模型
        weights = MobileNet_V2_Weights.DEFAULT
        self.model = models.mobilenet_v2(weights=weights)
        # 分类数量
        self.model.classifier[1] = nn.Linear(self.model.last_channel, len(self.class_map))
        # 加载训练好的权重
        self.model.load_state_dict(torch.load(model_path))
        self.model = self.model.to(self.device)
        self.model.eval()  # 设置为评估模式
    
    def recognize(self, image_path):
        """
        识别单个棋子图片
        :param image_path: 图片路径
        :return: 识别结果（如 'K', 'k', 'A', 'a' 等）
        """
        try:
            # 加载并预处理图像
            image = Image.open(image_path)
            image = self.transform(image).unsqueeze(0)  # 添加批次维度
            image = image.to(self.device)
            
            # 模型预测
            with torch.no_grad():
                outputs = self.model(image)
                _, predicted = torch.max(outputs, 1)
                predicted_idx = predicted.item()
            
            # 将数字转换为类别名称
            predicted_class = self.class_map[str(predicted_idx)]
            return predicted_class
            
        except Exception as e:
            print(f"识别图片时出错: {str(e)}")
            return None

# 使用示例
if __name__ == "__main__":
    # 创建识别器实例
    recognizer = ChessPieceRecognizer()
    
    # 测试识别
    test_image = "jj/red_K.jpg"
    result = recognizer.recognize(test_image)
    print(f"图片 {test_image} 的识别结果: {result}") 