import cv2
import numpy as np
import os
import threading
from app.tools.utils import app_cache_path, resource_path
from app.tools.log_config import get_logger
from app.chess.context import context as global_context
from app.chess.move_tracker import LegalMoveMatcher
from dataclasses import dataclass
from enum import Enum, auto

logger = get_logger(__name__)

class RecognitionErrorType(Enum):
    COVERED = auto()          # 动画遮挡
    LOW_CONFIDENCE = auto()   # 置信度低
    MARKER_MISSING = auto()   # 未检测到标记
    MASSIVE_CHANGE = auto()   # 巨大变化(可能是结算画面)
    UNKNOWN = auto()          # 未知错误

@dataclass
class RecognitionDetail:
    type: RecognitionErrorType
    position: tuple  # (row, col)
    message: str
    confidence: float = 0.0
    piece_type: str = None

class ChessRecognizer:
    def __init__(self, context=None):
        # 支持依赖注入，默认使用全局context
        self.context = context or global_context
        # 缓存上一帧的哈希和棋盘状态，用于增量识别
        self.last_grid_hashes = None
        self.last_board_array = None
        self.last_marker_coords = []  # 缓存标记位置
        self._jj_black_piece_templates = None
        self._recognition_lock = threading.RLock()
        self.move_matcher = LegalMoveMatcher()
        # 这组缓存只在 Checker 接受局面后提交，与“上一张看到
        # 的图”分离，避免误识别帧污染后续跟踪。
        self.trusted_grid_hashes = None
        self.trusted_board_array = None
        self.trusted_is_red_at_bottom = True
        self.trusted_side_to_move = None
        self._piece_drift_observations = {}

    def reset(self):
        """清除视觉与可信棋盘缓存，保留已加载模型。"""
        with self._recognition_lock:
            self.last_grid_hashes = None
            self.last_board_array = None
            self.last_marker_coords = []
            self.trusted_grid_hashes = None
            self.trusted_board_array = None
            self.trusted_is_red_at_bottom = True
            self.trusted_side_to_move = None
            self._piece_drift_observations = {}

    def commit_tracking_state(
        self, board_array, grid_hashes, is_red_at_bottom, side_to_move=None
    ):
        """Checker 通过规则与历史校验后，提交新的跟踪基准。"""
        if not board_array or not grid_hashes:
            return
        if len(board_array) != 10 or len(grid_hashes) != 10:
            return
        if any(len(row) != 9 for row in board_array):
            return
        if any(len(row) != 9 for row in grid_hashes):
            return
        with self._recognition_lock:
            self.trusted_board_array = [row[:] for row in board_array]
            self.trusted_grid_hashes = [row[:] for row in grid_hashes]
            self.trusted_is_red_at_bottom = bool(is_red_at_bottom)
            if side_to_move in ('red', 'black'):
                self.trusted_side_to_move = side_to_move

    def _confirm_fast_match(self, match, crops_by_position):
        """
        合法性只能用来提出候选，不能单独证明画面真的发生了
        这步棋。使用ONNX仅复核起点与终点：起点应为空位/标记，
        终点应为上一可信棋盘上的移动棋子。
        """
        src_crop = crops_by_position.get(match.from_pos)
        dst_crop = crops_by_position.get(match.to_pos)
        if src_crop is None or dst_crop is None:
            return False

        results = self.context.piece_recognizer.recognize_batch(
            [src_crop, dst_crop]
        )
        if len(results) != 2 or any(result is None for result in results):
            return False

        src_result, dst_result = results
        src_class = src_result.get('class_name')
        src_confidence = float(src_result.get('confidence', 0.0))
        dst_class = dst_result.get('class_name')
        dst_confidence = float(dst_result.get('confidence', 0.0))

        source_confirmed = (
            src_class in ('-', '.') and src_confidence >= 0.65
        )
        destination_confirmed = (
            dst_class == match.piece and dst_confidence >= 0.70
        )

        # 保留现有JJ黑炮视觉兜底，但只在规则候选本身就是
        # 黑炮时启用，不会把其他棋子补成黑炮。
        if not destination_confirmed and match.piece == 'c':
            destination_confirmed = self._recover_jj_black_cannon(
                dst_crop, previous_piece='c'
            )

        if not (source_confirmed and destination_confirmed):
            message = (
                f"合法着法候选视觉复核未通过: {match.piece} "
                f"{match.from_pos}->{match.to_pos}, "
                f"src={src_class}:{src_confidence:.2f}, "
                f"dst={dst_class}:{dst_confidence:.2f}"
            )
            logger.info(message)
            return False
        return True

    def _load_jj_black_piece_templates(self):
        """加载界面自带的黑方棋子图，供JJ模型漏检时进行轻量模板复核。"""
        if self._jj_black_piece_templates is not None:
            return self._jj_black_piece_templates

        templates = {}
        for piece in ("r", "n", "b", "a", "k", "c", "p"):
            path = resource_path("images", "media", f"black_{piece}.png")
            image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if image is None or image.ndim != 3 or image.shape[2] < 4:
                continue
            bgr = cv2.resize(image[:, :, :3], (80, 80))
            alpha = cv2.resize(image[:, :, 3], (80, 80)) > 128
            templates[piece] = (cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), alpha)
        self._jj_black_piece_templates = templates
        return templates

    def _stabilize_unexplained_piece_appearances(self, board_array):
        """回退无法由一步合法着法解释的凭空出现或原地变种棋子。"""
        trusted = self.trusted_board_array
        if self.context.platform != "JJ" or trusted is None:
            return board_array

        observed = [row[:] for row in board_array]
        observed_drift_keys = set()
        sources = []
        for row in range(10):
            for col in range(9):
                old_piece = trusted[row][col]
                if old_piece != "-" and observed[row][col] == "-":
                    sources.append((row, col))

        for row in range(10):
            for col in range(9):
                old_piece = trusted[row][col]
                new_piece = observed[row][col]
                if (
                    new_piece == old_piece
                    or not isinstance(new_piece, str)
                    or len(new_piece) != 1
                    or not new_piece.isalpha()
                ):
                    continue

                explained = False
                for source in sources:
                    source_row, source_col = source
                    if trusted[source_row][source_col] != new_piece:
                        continue
                    if self.trusted_side_to_move == "red" and not new_piece.isupper():
                        continue
                    if self.trusted_side_to_move == "black" and new_piece.isupper():
                        continue
                    predicted = [trusted_row[:] for trusted_row in trusted]
                    predicted[source_row][source_col] = "-"
                    predicted[row][col] = new_piece
                    if self.move_matcher._rules.is_step_legal(
                        trusted,
                        predicted,
                        self.trusted_is_red_at_bottom,
                        {
                            "from_pos": source,
                            "to_pos": (row, col),
                            "piece": new_piece,
                        },
                    ):
                        explained = True
                        break

                if not explained:
                    drift_key = ((row, col), old_piece, new_piece)
                    observed_drift_keys.add(drift_key)
                    drift_count = self._piece_drift_observations.get(drift_key, 0) + 1
                    self._piece_drift_observations[drift_key] = drift_count
                    if drift_count < 3:
                        logger.info(
                            "回退无法解释的棋子类别变化: "
                            f"position=({row}, {col}), trusted={old_piece}, "
                            f"predicted={new_piece}, repeat={drift_count}/3"
                        )
                        observed[row][col] = old_piece
                    else:
                        logger.warning(
                            "连续视觉证据允许类别重同步: "
                            f"position=({row}, {col}), trusted={old_piece}, "
                            f"predicted={new_piece}, repeat={drift_count}"
                        )

        self._piece_drift_observations = {
            key: count
            for key, count in self._piece_drift_observations.items()
            if key in observed_drift_keys
        }

        return observed

    @staticmethod
    def _contains_centered_piece_circle(piece_img):
        if piece_img is None or min(piece_img.shape[:2]) < 40:
            return False
        gray = cv2.cvtColor(piece_img[:, :, :3], cv2.COLOR_BGR2GRAY)
        height, width = gray.shape
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1,
            minDist=max(10, min(width, height) // 3),
            param1=80,
            param2=18,
            minRadius=max(10, int(min(width, height) * 0.34)),
            maxRadius=max(12, int(min(width, height) * 0.51)),
        )
        if circles is None:
            return False
        center_x, center_y = width / 2, height / 2
        tolerance = min(width, height) * 0.18
        return any(
            abs(float(x) - center_x) <= tolerance
            and abs(float(y) - center_y) <= tolerance
            for x, y, _ in circles[0]
        )

    @staticmethod
    def _has_black_ink(piece_img):
        """区分黑色字形与红色字形，避免把红炮补成黑炮。"""
        height, width = piece_img.shape[:2]
        y_margin = max(1, int(height * 0.18))
        x_margin = max(1, int(width * 0.18))
        center = piece_img[y_margin:height-y_margin, x_margin:width-x_margin, :3]
        hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
        hue, saturation, value = cv2.split(hsv)
        dark_neutral = ((value < 110) & (saturation < 130)).mean()
        red_ink = (
            ((hue < 12) | (hue > 170))
            & (saturation > 100)
            & (value > 80)
        ).mean()
        return dark_neutral >= 0.08 and dark_neutral > red_ink * 1.5

    def _recover_jj_black_cannon(
        self,
        piece_img,
        previous_piece="-",
        *,
        position=None,
        model_piece=None,
    ):
        """以圆形、字色、棋规位置和模板证据恢复被误判的 JJ 黑炮。"""
        if self.context.platform != "JJ":
            return False
        if not self._contains_centered_piece_circle(piece_img):
            return False
        if not self._has_black_ink(piece_img):
            return False
        if previous_piece == "c":
            return True
        # 黑将只能位于上下九宫的中间三列。正式 JJ 模型已知会把部分
        # 黑炮判成 k；若该格根本不可能是将位，圆形和黑色字形足以排除
        # 空格/标记，再按这个已知混淆恢复为黑炮。
        if model_piece == "k" and position is not None:
            row, col = position
            inside_palace = (row <= 2 or row >= 7) and 3 <= col <= 5
            if not inside_palace:
                return True

        templates = self._load_jj_black_piece_templates()
        if "c" not in templates:
            return False
        actual = cv2.cvtColor(
            cv2.resize(piece_img[:, :, :3], (80, 80)),
            cv2.COLOR_BGR2GRAY,
        )
        scores = {}
        for piece, (template, mask) in templates.items():
            actual_values = actual[mask].astype(np.float32)
            template_values = template[mask].astype(np.float32)
            if actual_values.std() < 1e-6 or template_values.std() < 1e-6:
                continue
            scores[piece] = float(np.corrcoef(actual_values, template_values)[0, 1])
        cannon_score = scores.get("c", -1.0)
        other_best = max((v for k, v in scores.items() if k != "c"), default=-1.0)
        return cannon_score >= 0.20 and cannon_score - other_best >= 0.05

    def preprocess_image(self, img_origin):
        # img = cv2.imread(img_path)  
        img_np = np.frombuffer(img_origin.bgra, np.uint8).reshape(img_origin.height, img_origin.width, 4)
        img_np = img_np[:, :, :3]  # 去掉 alpha 通道
        if img_np is None:  
            logger.error("npImage is None.")
            return  None, None 
        new_width = 800  
        scale_factor = new_width / img_np.shape[1]  # 注意使用宽度来计算缩放因子  
        new_height = int(img_np.shape[0] * scale_factor)  
        resized_img = cv2.resize(img_np, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
        # cv2.imwrite('./chess_assistant/app/uploads/图像.png', resized_img)
        # print(f"图片宽高是:{img.shape[1]} x {img.shape[0]}")
        # 灰度化  
        gray = cv2.cvtColor(resized_img, cv2.COLOR_BGR2GRAY) 
        return resized_img, gray

    def recognize_piece_from_grid(self, img, x_array, y_array):
        # 两个处理工作线程共享同一识别器。缓存读取、模型推理和
        # 缓存写回必须是一个原子过程，否则帧会交叉覆盖上一局面。
        with self._recognition_lock:
            return self._recognize_piece_from_grid_locked(img, x_array, y_array)

    def _recognize_piece_from_grid_locked(self, img, x_array, y_array):
        """
        切割棋盘格点识别棋子，返回9x10棋盘数组和红黑方
        Args:
            img: 原始图像
            x_array: 棋盘横线坐标数组
            y_array: 棋盘纵线坐标数组
        Returns:
            (pieceArray, marker_coords, current_grid_hashes): 
                pieceArray: 9x10的二维数组
                marker_coords: 标记坐标 (由CNN识别的 '.' 类型)
                current_grid_hashes: 哈希
        """
        from app.tools.utils import compute_image_hash

        # JJ增量识别必须始终从Checker已经接受的可信局面出发。旧实现
        # 会把被Checker拒绝的“第三个黑士”等结果写进last缓存，下一帧
        # 哈希命中后永久复用错误类别，形成无法自愈的重拍循环。
        if (
            self.context.platform == "JJ"
            and self.trusted_grid_hashes is not None
            and self.trusted_board_array is not None
        ):
            last_grid_hashes = self.trusted_grid_hashes
            last_board_array = self.trusted_board_array
            last_marker_coords = []
        else:
            last_grid_hashes = self.last_grid_hashes
            last_board_array = self.last_board_array
            last_marker_coords = self.last_marker_coords or []

        # 预处理
        resized_img, gray = self.preprocess_image(img)
        
        # 初始化结果数组
        pieceArray = [["-"] * len(x_array) for _ in range(len(y_array))]
        current_grid_hashes = [([None] * len(x_array)) for _ in range(len(y_array))]
        
        # CNN 检测到的标记位置
        marker_coords = []
        
        # 收集识别过程中的错误/警告
        details = []
        
        # 创建保存目录
        save_dir = app_cache_path("pieces")
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError:
            # 如果无法创建目录，跳过保存调试图片
            save_dir = None
        
        # 准备批量识别
        crops = []
        positions = []  # 与 crops 对应，存 (i, j)
        crops_by_position = {}
        
        # 统计增量识别效果
        cached_count = 0
        predicted_count = 0
        
        for i in range(len(y_array)):
            for j in range(len(x_array)):
                center_x = x_array[j]
                center_y = y_array[i]
                # 计算当前位置的切割半径
                if j == 0:
                    x_radius = (x_array[j+1] - x_array[j]) // 2
                elif j == len(x_array)-1:
                    x_radius = (x_array[j] - x_array[j-1]) // 2
                else:
                    x_radius = min((x_array[j] - x_array[j-1]) // 2, (x_array[j+1] - x_array[j]) // 2)
                if i == 0:
                    y_radius = (y_array[i+1] - y_array[i]) // 2
                elif i == len(y_array)-1:
                    y_radius = (y_array[i] - y_array[i-1]) // 2
                else:
                    y_radius = min((y_array[i] - y_array[i-1]) // 2, (y_array[i+1] - y_array[i]) // 2)
                # JJ 新版棋子外圈和阴影更宽。沿用 0.95 会把过多背景缩进
                # 80x80 模型输入，黑炮等字形会被误判；稍微收紧后模型能
                # 聚焦棋子文字。TT 保持原比例，避免改变已有识别效果。
                crop_scale = 0.85 if self.context.platform == "JJ" else 0.95
                cut_radius = int((x_radius + y_radius) // 2 * crop_scale)
                adjusted_center_x = max(cut_radius, min(resized_img.shape[1] - 1 - cut_radius, center_x))
                adjusted_center_y = max(cut_radius, min(resized_img.shape[0] - 1 - cut_radius, center_y))
                x1 = adjusted_center_x - cut_radius
                y1 = adjusted_center_y - cut_radius
                x2 = adjusted_center_x + cut_radius
                y2 = adjusted_center_y + cut_radius
                piece_img = resized_img[y1:y2, x1:x2]
                crops_by_position[(i, j)] = piece_img
                
                # 计算当前格子的哈希
                curr_hash = compute_image_hash(piece_img)
                current_grid_hashes[i][j] = curr_hash
                
                # 检查缓存命中
                is_hit = False
                if last_grid_hashes and last_board_array and curr_hash:
                    last_h = last_grid_hashes[i][j]
                    if last_h == curr_hash:
                        pieceArray[i][j] = last_board_array[i][j]
                        # 如果上一帧该位置是标记，继续保留标记状态
                        if (i, j) in last_marker_coords:
                            marker_coords.append((i, j))
                        is_hit = True
                        cached_count += 1
                
                # 未命中缓存，加入待识别队列
                if not is_hit:
                    crops.append(piece_img)
                    positions.append((i, j))
                    predicted_count += 1
        
        # JJ快速路径：不识别变化格的类别，而是尝试用唯一的
        # 合法着法解释这些视觉变化。匹配失败时继续执行原有
        # 局部批量ONNX识别。
        fast_match = None
        if (
            self.context.platform == "JJ"
            and self.trusted_board_array is not None
            and self.trusted_grid_hashes is not None
        ):
            fast_match = self.move_matcher.match(
                self.trusted_board_array,
                self.trusted_grid_hashes,
                current_grid_hashes,
                self.trusted_is_red_at_bottom,
                self.trusted_side_to_move,
            )

        if (
            fast_match is not None
            and self._confirm_fast_match(fast_match, crops_by_position)
        ):
            pieceArray = [row[:] for row in fast_match.board]
            marker_coords = []
            details.append(RecognitionDetail(
                type=RecognitionErrorType.MARKER_MISSING,
                position=(-1, -1),
                message=(
                    f"合法着法快速匹配: {fast_match.from_pos} -> "
                    f"{fast_match.to_pos}, score={fast_match.score}, "
                    f"margin={fast_match.margin}"
                ),
                confidence=1.0,
                piece_type=fast_match.piece,
            ))
            message = (
                f"合法着法视觉快速路径: {fast_match.piece} "
                f"{fast_match.from_pos}->{fast_match.to_pos}, "
                f"changed={fast_match.changed_positions}, score={fast_match.score}"
            )
            logger.info(message)
            self.last_grid_hashes = current_grid_hashes
            self.last_board_array = pieceArray
            self.last_marker_coords = []
            return pieceArray, marker_coords, current_grid_hashes, details

        if crops:
            logger.debug(f"增量识别: 缓存命中 {cached_count} 格, 哈希变动(重算) {predicted_count} 格")
            batch_results = self.context.piece_recognizer.recognize_batch(crops)
            for idx, res in enumerate(batch_results):
                i, j = positions[idx]
                piece_img = crops[idx]
                if res is None:
                    details.append(RecognitionDetail(
                        type=RecognitionErrorType.UNKNOWN,
                        position=(i, j),
                        message=f"批量识别失败: 结果为None at ({i},{j})",
                        confidence=0.0
                    ))
                    continue
                    
                piece_type = res['class_name']
                confidence = res['confidence']
                previous_piece = (
                    last_board_array[i][j]
                    if last_board_array is not None
                    else '-'
                )
                # JJ 黑炮偶尔会被正式模型高置信度误判为黑将；仅对空格、
                # 低置信度和这一种已知混淆执行圆形/字色/模板三重复核。
                # 其他高置信度棋子直接采用，避免上一帧状态覆盖本帧结果。
                if (
                    (piece_type in ('-', 'k') or confidence <= 0.6)
                    and self._recover_jj_black_cannon(
                        piece_img,
                        previous_piece,
                        position=(i, j),
                        model_piece=piece_type,
                    )
                ):
                    piece_type = 'c'
                    confidence = max(float(confidence), 0.75)
                    logger.warning(
                        f"JJ黑炮视觉兜底: position=({i}, {j}), "
                        f"model_class={res['class_name']!r}, previous={previous_piece!r}"
                    )

                if piece_type and confidence > 0.6:
                    if piece_type == 'covered':
                        details.append(RecognitionDetail(
                            type=RecognitionErrorType.COVERED,
                            position=(i, j),
                            message=f"动画遮挡 at ({i},{j})",
                            confidence=confidence,
                            piece_type=piece_type
                        ))
                        # 动画遮挡时不更新棋盘状态,保留'-'
                        continue
                    
                    # 检测标记：模型识别为 '.' 的位置
                    if piece_type == '.':
                        marker_coords.append((i, j))
                        logger.debug(f"CNN检测到标记 at ({i+1}, {j+1}) conf={confidence:.2f}")  # 1-indexed for readability
                        pieceArray[i][j] = '-'  # 标记位置的棋子标记为空
                    else:
                        pieceArray[i][j] = piece_type
                        # 调试：显示非标记的识别结果，帮助排查漏检
                        # print(f"Debug - CNN识别 ({i+1}, {j+1}): {piece_type} conf={confidence:.2f}")
                else:
                    # 低置信度：记录错误，但不要把不可靠的猜测写入棋盘。
                    # 有上一帧时保留该格状态；首次识别则维持为空，等待后续
                    # 稳定帧重新识别。这样可避免一个误判造成非法棋子数量。
                    details.append(RecognitionDetail(
                        type=RecognitionErrorType.LOW_CONFIDENCE,
                        position=(i, j),
                        message=f"低置信度 at ({i},{j}): {piece_type} - {confidence:.2f}",
                        confidence=confidence,
                        piece_type=piece_type
                    ))
                    if last_board_array:
                        pieceArray[i][j] = last_board_array[i][j]
                    # 不缓存本次不可靠结果，确保下一稳定帧会重新推理该格。
                    current_grid_hashes[i][j] = None
        else:
            # 全部命中缓存
            # print("Debug - 全局缓存命中，跳过CNN识别")
            pass

        pieceArray = self._stabilize_unexplained_piece_appearances(pieceArray)

        # 检查是否无标记 (新增 MARKER_MISSING 检测)
        if not marker_coords:
            details.append(RecognitionDetail(
                type=RecognitionErrorType.MARKER_MISSING,
                position=(-1, -1),
                message=f"未检测到标记 (Hash变动: {predicted_count}格)",
                confidence=1.0
            ))
        
        # 检查是否巨大变化 (可能是结算画面)
        if predicted_count > 45:
            details.append(RecognitionDetail(
                type=RecognitionErrorType.MASSIVE_CHANGE,
                position=(-1, -1),
                message=f"巨大变化 ({predicted_count}格)",
                confidence=1.0
            ))

        # 打印时转换为 1-indexed 方便阅读
        display_coords = [(r+1, c+1) for r, c in marker_coords]
        logger.debug(
            f"移动标记: count={len(marker_coords)}, positions={display_coords}"
        )
        
        # 更新内部缓存
        self.last_grid_hashes = current_grid_hashes
        self.last_board_array = pieceArray
        self.last_marker_coords = marker_coords  # 缓存标记位置
        
        return pieceArray, marker_coords, current_grid_hashes, details

    def recognize_piece_type(self, piece_img):
        """
        识别棋子类型
        :param piece_img: 棋子图片
        :return: 棋子类型, 置信度或None
        """
        try:
            result = self.context.piece_recognizer.recognize_from_array(piece_img)
            if result is None:
                return None
            return result['class_name'], result['confidence']
        except Exception as e:
            logger.error(f"棋子识别过程中出错: {e}")
            return None
