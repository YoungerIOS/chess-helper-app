import torch
import torchvision.transforms as transforms
from torchvision import models
from torchvision.models import MobileNet_V2_Weights
import torch.nn as nn
from PIL import Image
import os

class CountdownPredictor:
    def __init__(self, model_path="countdown_model.pth"):
        """初始化预测器
        
        Args:
            model_path: 模型文件路径
        """
        # 设置设备
        self.device = torch.device("mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu")
        
        # 设置类别名称（修改映射关系）
        self.class_names = ['countdown', 'normal']  # 0: countdown, 1: normal
        
        # 加载模型
        self.model = self._load_model(model_path)
        self.model = self.model.to(self.device)
        
        # 设置图像预处理
        self.transform = transforms.Compose([
            self.CropBottomSquare(),
            transforms.Resize((96, 96)),
            transforms.ToTensor()
        ])
    
    class CropBottomSquare:
        def __call__(self, img):
            width, height = img.size
            side = min(width, height)
            top = height - side  # 从顶部裁去
            return transforms.functional.crop(img, top, 0, side, side)
    
    def _load_model(self, model_path):
        """加载模型"""
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"找不到模型文件: {model_path}")
        
        weights = MobileNet_V2_Weights.DEFAULT
        model = models.mobilenet_v2(weights=weights)
        model.classifier[1] = nn.Linear(model.last_channel, 2)

        model.load_state_dict(torch.load(model_path))
        model.eval()
        return model
    
    def predict(self, image_path):
        """预测单张图片
        
        Args:
            image_path: 图片路径
            
        Returns:
            dict: 包含预测结果的字典
                - class_name: 预测的类别名称 ('countdown' 或 'normal')
                - confidence: 预测的置信度
                - class_index: 预测的类别索引 (0: countdown, 1: normal)
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"找不到图片: {image_path}")
        
        # 加载并转换图像
        image = Image.open(image_path).convert('RGB')
        image_tensor = self.transform(image).unsqueeze(0).to(self.device)
        
        # 预测
        with torch.no_grad():
            outputs = self.model(image_tensor)
            probabilities = torch.nn.functional.softmax(outputs, dim=1)
            predicted_class = outputs.argmax(1).item()
            confidence = probabilities[0][predicted_class].item()
        
        return {
            'class_name': self.class_names[predicted_class],
            'confidence': confidence,
            'class_index': predicted_class
        }

# 使用示例
if __name__ == '__main__':
    # 创建预测器实例
    predictor = CountdownPredictor()
    
    # 预测单张图片
    result = predictor.predict('path/to/your/image.jpg')
    print(f"预测状态: {result['class_name']}")
    print(f"置信度: {result['confidence']:.2%}") 