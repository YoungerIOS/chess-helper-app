import json
import glob
import numpy as np
import onnxruntime as ort
from PIL import Image
from app.tools.utils import resource_path
from app.tools.log_config import get_logger


logger = get_logger(__name__)

class ChessPieceRecognizer:
    def __init__(self, platform="TT"):
        """
        初始化棋子识别器 (基于 ONNX Runtime)
        :param platform: 游戏平台，"TT"表示天天象棋，"JJ"表示JJ象棋
        """
        # 根据平台选择模型类型
        model_type = "tt" if platform == "TT" else "jj"
        
        # 使用 .onnx 模型而不是 .pth
        self.model_path = resource_path("models", f"{model_type}_piece_model.onnx")
        self.class_map_path = resource_path("models", f"{model_type}_piece_map.json")
        
        # 加载类别映射
        with open(self.class_map_path, "r", encoding="utf-8") as f:
            self.class_map = json.load(f)
        
        # 创建 ONNX Runtime 推理会话 w/ CPUExecutionProvider (避免依赖 CoreML/CUDA)
        self.session = ort.InferenceSession(
            self.model_path, 
            providers=['CPUExecutionProvider'] 
        )
        self.input_name = self.session.get_inputs()[0].name
        
    def _preprocess(self, image_array_or_pil):
        """
        将图像预处理为模型输入格式 (Batch, Channel, Height, Width) 的 np.float32 数组。
        步骤: Resize(80x80) -> ToTensor(Norm 0-1) -> Transpose(HWC->CHW) -> Batch dim
        """
        # 1. 统一转为 PIL 并 Resize
        if isinstance(image_array_or_pil, Image.Image):
            pil_img = image_array_or_pil
        else:
            # numpy array (H, W, C) from OpenCV (BGR)
            arr = image_array_or_pil
            if not isinstance(arr, np.ndarray):
                raise ValueError("Unsupported image type for _preprocess")
            
            # 去掉 alpha 通道
            if arr.ndim == 3 and arr.shape[2] == 4:
                arr = arr[:, :, :3]
                
            # BGR -> RGB
            arr = arr[:, :, ::-1]
            pil_img = Image.fromarray(arr)
            
        # Resize to 80x80 (Bilinear default)
        pil_img = pil_img.resize((80, 80), Image.BILINEAR)
        
        # 2. Convert to Numpy Float32 & Normalize [0, 1]
        # (80, 80, 3)
        img_data = np.array(pil_img, dtype=np.float32) / 255.0
        
        # 3. Transpose (H, W, C) -> (C, H, W)
        # (3, 80, 80)
        img_data = np.transpose(img_data, (2, 0, 1))
        
        # 4. Add Batch Dimension -> (1, 3, 80, 80)
        img_data = np.expand_dims(img_data, axis=0)
        
        # Ensure contiguous array for safety
        return np.ascontiguousarray(img_data)

    def recognize_from_array(self, image_array_or_pil):
        """直接对内存中的图像进行识别"""
        try:
            # 预处理
            input_data = self._preprocess(image_array_or_pil)
            
            # 推理
            outputs = self.session.run(None, {self.input_name: input_data})
            logits = outputs[0][0]  # (Num_Classes, )
            
            # Softmax & Argmax using Numpy
            exp_logits = np.exp(logits - np.max(logits)) # Stability
            probabilities = exp_logits / np.sum(exp_logits)
            
            predicted_idx = np.argmax(probabilities)
            confidence = probabilities[predicted_idx]
            
            predicted_class = self.class_map[str(predicted_idx)]
            
            return {
                'class_name': predicted_class,
                'confidence': float(confidence),
                'class_index': int(predicted_idx)
            }
        except Exception as e:
            logger.exception("内存图像识别失败")
            return None

    def recognize_batch(self, image_arrays_or_pils):
        """对一批内存图像进行批量识别"""
        if not image_arrays_or_pils:
            return []
            
        batch_tensors = []
        results = [None] * len(image_arrays_or_pils)
        valid_indices = []
        
        # 1. 批量预处理
        for idx, img in enumerate(image_arrays_or_pils):
            try:
                # _preprocess returns (1, 3, 80, 80)
                t = self._preprocess(img)
                batch_tensors.append(t)
                valid_indices.append(idx)
            except Exception as e:
                logger.exception(f"批量预处理失败: idx={idx}")
                results[idx] = None

        if not batch_tensors:
            return results
            
        # 2. Stack -> (Batch, 3, 80, 80)
        batch_input = np.concatenate(batch_tensors, axis=0)
        
        try:
            # 3. 推理
            outputs = self.session.run(None, {self.input_name: batch_input})
            batch_logits = outputs[0] # (Batch, Num_Classes)
            
            # 4. Post-process
            for i, base_idx in enumerate(valid_indices):
                logits = batch_logits[i]
                
                # Softmax
                exp_logits = np.exp(logits - np.max(logits))
                probabilities = exp_logits / np.sum(exp_logits)
                
                predicted_idx = np.argmax(probabilities)
                confidence = probabilities[predicted_idx]
                predicted_class = self.class_map[str(predicted_idx)]
                
                results[base_idx] = {
                    'class_name': predicted_class,
                    'confidence': float(confidence),
                    'class_index': int(predicted_idx)
                }
                
        except Exception as e:
            logger.exception("批量推理失败")
            
        return results

    def recognize(self, image_path):
        """识别单个棋子图片"""
        try:
            image = Image.open(image_path)
            return self.recognize_from_array(image)
        except Exception as e:
            logger.exception("识别图片失败")
            return None

# 使用示例
if __name__ == "__main__":
    # 创建TT识别器实例
    tt_recognizer = ChessPieceRecognizer(platform="TT")
    print("\n测试TT识别器 (ONNX)...")
    test_images_tt = glob.glob("test_images/*.jpg")
    test_images_tt.sort()  # 按文件名排序
    for img_path in test_images_tt:
        result = tt_recognizer.recognize(img_path)
        print(f"图片: {img_path}")
        print(f"识别结果: {result}")
        print("-" * 50)
