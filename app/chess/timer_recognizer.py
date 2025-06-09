import torch
import torchvision.transforms as transforms
from torchvision import models
from torchvision.models import MobileNet_V2_Weights
import torch.nn as nn
from PIL import Image
import os
import glob
from tools.utils import resource_path

class CountdownPredictor:
    def __init__(self, platform="TT"):
        """初始化预测器
        
        Args:
            platform: 平台名称 ('TT' 或 'JJ')
        """
        # 设置设备
        self.device = torch.device("mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu")
        print(f"使用设备: {self.device}")
        
        # 设置类别名称
        self.class_names = ['countdown', 'normal']  # 根据实际数据集修改
        
        # 根据平台选择模型路径
        if platform == "TT":
            model_path = resource_path("models/tt_countdown_model.pth")
        else:  # JJ
            model_path = resource_path("models/jj_countdown_model.pth")
        
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
        model.classifier[1] = nn.Linear(model.last_channel, len(self.class_names))
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
    predictor = CountdownPredictor(platform="TT")
    
    # 测试数据集中的图片
    test_dirs = [
        "countdown_tt/test_images",
    ]
    
    print("\n开始测试预测...")
    for test_dir in test_dirs:
        print(f"\n测试目录: {test_dir}")
        print("-" * 50)
        
        # 获取目录下所有图片
        image_files = glob.glob(os.path.join(test_dir, "*.jpg")) + glob.glob(os.path.join(test_dir, "*.png"))
        image_files.sort()  # 按文件名排序
        
        # 预测每张图片
        for img_path in image_files:
            try:
                result = predictor.predict(img_path)
                print(f"图片: {os.path.basename(img_path)}")
                print(f"预测状态: {result['class_name']}")
                print(f"置信度: {result['confidence']:.2%}")
                print("-" * 30)
            except Exception as e:
                print(f"处理图片 {img_path} 时出错: {str(e)}") 