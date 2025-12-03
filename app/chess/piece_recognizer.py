import json
import glob
import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image
from app.tools.utils import resource_path

class ChessPieceRecognizer:
    def __init__(self, platform="TT"):
        """
        初始化棋子识别器
        :param platform: 游戏平台，"TT"表示天天象棋，"JJ"表示JJ象棋
        """
        # 检测设备
        self.device = (
            torch.device("mps") if torch.backends.mps.is_available()
            else torch.device("cuda" if torch.cuda.is_available() else "cpu")
        )
        
        # 根据平台选择模型类型
        model_type = "tt" if platform == "TT" else "jj"
        self.model_path = resource_path("models", f"{model_type}_piece_model.pth")
        self.class_map_path = resource_path("models", f"{model_type}_piece_map.json")
        
        # 图像预处理
        self.transform = transforms.Compose([
            transforms.Resize((80, 80)),
            transforms.ToTensor(),
        ])
        
        # 加载类别映射
        with open(self.class_map_path, "r", encoding="utf-8") as f:
            self.class_map = json.load(f)
        
        # 加载模型
        self.model = models.mobilenet_v2(weights=None)  # 使用新的 weights 参数
        self.model.classifier[1] = nn.Linear(self.model.last_channel, len(self.class_map))
        self.model.load_state_dict(torch.load(self.model_path))
        self.model = self.model.to(self.device)
        self.model.eval()  # 设置为评估模式
    
    def _to_tensor(self, image_array_or_pil):
        """
        将 numpy(BGR) 或 PIL 图像转换为模型输入 tensor（不包含 batch 维度）。
        """
        if isinstance(image_array_or_pil, Image.Image):
            pil_img = image_array_or_pil
        else:
            import numpy as np
            # 处理 numpy 数组 (H, W, C)。若来自 OpenCV 则通常为 BGR，需要转为 RGB
            arr = image_array_or_pil
            if not isinstance(arr, np.ndarray):
                raise ValueError("Unsupported image type for _to_tensor")
            if arr.ndim != 3 or arr.shape[2] not in (3, 4):
                raise ValueError("Expect HxWx3/4 image array")
            if arr.shape[2] == 4:
                arr = arr[:, :, :3]
            # BGR -> RGB
            arr = arr[:, :, ::-1]
            pil_img = Image.fromarray(arr)
        tensor = self.transform(pil_img)
        return tensor

    def recognize_from_array(self, image_array_or_pil):
        """
        直接对内存中的图像进行识别。
        :param image_array_or_pil: numpy 数组(BGR/RGB) 或 PIL.Image
        :return: 与 recognize(image_path) 相同的字典格式，或 None
        """
        try:
            image = self._to_tensor(image_array_or_pil).unsqueeze(0).to(self.device)
            with torch.no_grad():
                outputs = self.model(image)
                probabilities = torch.nn.functional.softmax(outputs, dim=1)
                _, predicted = torch.max(outputs, 1)
                predicted_idx = predicted.item()
                confidence = probabilities[0][predicted_idx].item()
            predicted_class = self.class_map[str(predicted_idx)]
            return {
                'class_name': predicted_class,
                'confidence': confidence,
                'class_index': predicted_idx
            }
        except Exception as e:
            print(f"内存图像识别时出错: {str(e)}")
            return None

    def recognize_batch(self, image_arrays_or_pils):
        """
        对一批内存图像进行批量识别。
        :param image_arrays_or_pils: list[numpy 或 PIL.Image]
        :return: list[dict 或 None]，与 recognize() 返回格式一致
        """
        if not image_arrays_or_pils:
            return []
        tensors = []
        results = [None] * len(image_arrays_or_pils)
        index_map = []
        for idx, img in enumerate(image_arrays_or_pils):
            try:
                t = self._to_tensor(img)
                tensors.append(t)
                index_map.append(idx)
            except Exception as e:
                # 保持该位置为 None
                print(f"批量预处理失败 idx={idx}: {e}")
                results[idx] = None
        if not tensors:
            return results
        batch = torch.stack(tensors, dim=0).to(self.device)
        try:
            with torch.no_grad():
                outputs = self.model(batch)
                probabilities = torch.nn.functional.softmax(outputs, dim=1)
                conf_values, predicted = torch.max(probabilities, dim=1)
                for j, base_idx in enumerate(index_map):
                    predicted_idx = predicted[j].item()
                    confidence = conf_values[j].item()
                    predicted_class = self.class_map[str(predicted_idx)]
                    results[base_idx] = {
                        'class_name': predicted_class,
                        'confidence': confidence,
                        'class_index': predicted_idx
                    }
        except Exception as e:
            print(f"批量推理失败: {e}")
        return results

    def recognize(self, image_path):
        """
        识别单个棋子图片
        :param image_path: 图片路径
        :return: 字典，包含识别结果和置信度
            - class_name: 识别结果（如 'K', 'k', 'A', 'a' 等）
            - confidence: 置信度（0-1之间的浮点数）
            - class_index: 预测的类别索引
        """
        try:
            # 加载并预处理图像
            image = Image.open(image_path)
            image = self.transform(image).unsqueeze(0)  # 添加批次维度
            image = image.to(self.device)
            
            # 模型预测
            with torch.no_grad():
                outputs = self.model(image)
                probabilities = torch.nn.functional.softmax(outputs, dim=1)
                _, predicted = torch.max(outputs, 1)
                predicted_idx = predicted.item()
                confidence = probabilities[0][predicted_idx].item()
            
            # 将数字转换为类别名称
            predicted_class = self.class_map[str(predicted_idx)]
            return {
                'class_name': predicted_class,
                'confidence': confidence,
                'class_index': predicted_idx
            }
            
        except Exception as e:
            print(f"识别图片时出错: {str(e)}")
            return None

# 使用示例
if __name__ == "__main__":
    # 创建JJ识别器实例
    # jj_recognizer = ChessPieceRecognizer(model_type="jj")
    # print("\n测试JJ识别器...")
    # test_images_jj = glob.glob("test_images/jj/*.jpg")
    # test_images_jj.sort()  # 按文件名排序
    # for img_path in test_images_jj:
    #     result = jj_recognizer.recognize(img_path)
    #     print(f"图片: {img_path}")
    #     print(f"识别结果: {result}")
    #     print("-" * 50)
    
    # 创建TT识别器实例
    tt_recognizer = ChessPieceRecognizer(platform="TT")
    print("\n测试TT识别器...")
    test_images_tt = glob.glob("test_images/*.jpg")
    test_images_tt.sort()  # 按文件名排序
    for img_path in test_images_tt:
        result = tt_recognizer.recognize(img_path)
        print(f"图片: {img_path}")
        print(f"识别结果: {result}")
        print("-" * 50) 