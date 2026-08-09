from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from app.tools.log_config import get_logger

logger = get_logger(__name__)

@dataclass
class BoardStatus:
    is_illegal_board: bool = False  # 非法局面：棋子数量或位置非法
    is_illegal_change: bool = False   # 非法变化：变化无法解析
    is_same_board: bool = False
    is_my_step: bool = False
    is_opponent_step: bool = False
    is_multi_step: bool  = False
    is_new_game: bool = False 
    is_red_start: bool = False
    is_black_start: bool = False
    is_history_mismatch: bool = False # 历史校验是否不一致
    step_info: Optional[Dict[str, Any]] = field(default_factory=dict)
    message: str = ""
    
    @property
    def is_active(self) -> bool:
        """
        判断是否为有效的活跃状态
        Active includes: Valid moves, New Game, Same Board (Thinking)
        Excluded: Illegal boards, Illegal changes, Mismatches, Multi-step
        """
        return not (self.is_illegal_board or 
                    self.is_illegal_change or 
                    self.is_history_mismatch or 
                    self.is_multi_step)
    

class PositionChecker:
    # 类变量，整个类都可以访问
    START_RED = [
        ['r', 'n', 'b', 'a', 'k', 'a', 'b', 'n', 'r'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['-', 'c', '-', '-', '-', '-', '-', 'c', '-'],
        ['p', '-', 'p', '-', 'p', '-', 'p', '-', 'p'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['P', '-', 'P', '-', 'P', '-', 'P', '-', 'P'],
        ['-', 'C', '-', '-', '-', '-', '-', 'C', '-'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['R', 'N', 'B', 'A', 'K', 'A', 'B', 'N', 'R']
    ]
    
    # 红方在上面的初始局面（黑方在下面）
    START_BLACK = [
        ['R', 'N', 'B', 'A', 'K', 'A', 'B', 'N', 'R'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['-', 'C', '-', '-', '-', '-', '-', 'C', '-'],
        ['P', '-', 'P', '-', 'P', '-', 'P', '-', 'P'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['p', '-', 'p', '-', 'p', '-', 'p', '-', 'p'],
        ['-', 'c', '-', '-', '-', '-', '-', 'c', '-'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['r', 'n', 'b', 'a', 'k', 'a', 'b', 'n', 'r']
    ]

    START_COUNTS = {
        'r': 2, 'n': 2, 'b': 2, 'a': 2, 'k': 1, 'c': 2, 'p': 5,
        'R': 2, 'N': 2, 'B': 2, 'A': 2, 'K': 1, 'C': 2, 'P': 5
    }

    START_JIEQI_RED = [
        ['x', 'x', 'x', 'x', 'k', 'x', 'x', 'x', 'x'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['-', 'x', '-', '-', '-', '-', '-', 'x', '-'],
        ['x', '-', 'x', '-', 'x', '-', 'x', '-', 'x'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['X', '-', 'X', '-', 'X', '-', 'X', '-', 'X'],
        ['-', 'X', '-', '-', '-', '-', '-', 'X', '-'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['X', 'X', 'X', 'X', 'K', 'X', 'X', 'X', 'X'],
    ]
    START_JIEQI_BLACK = [
        ['X', 'X', 'X', 'X', 'K', 'X', 'X', 'X', 'X'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['-', 'X', '-', '-', '-', '-', '-', 'X', '-'],
        ['X', '-', 'X', '-', 'X', '-', 'X', '-', 'X'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['x', '-', 'x', '-', 'x', '-', 'x', '-', 'x'],
        ['-', 'x', '-', '-', '-', '-', '-', 'x', '-'],
        ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
        ['x', 'x', 'x', 'x', 'k', 'x', 'x', 'x', 'x'],
    ]
    JIEQI_COUNTS = {**START_COUNTS, 'x': 15, 'X': 15}

    def __init__(self, variant="xiangqi"):
        self.variant = variant if variant in ("xiangqi", "jieqi") else "xiangqi"
        self.is_red = True
        self.last_board = None  # 上一次的棋盘数组
        self.last_counts = None  # 上一次的棋子数量统计
        self.red_start_count = 0  # 红方开局帧连续出现次数 
        self.consecutive_drops = 0 # 连续丢帧重拍计数(防卡死)
        self.consecutive_mismatches = 0 # 连续历史校验不一致计数
        self.in_settlement_screen = False  # 是否处于结算画面状态
        self.capture_depth_bonus = 0  # 本局我方被吃棋子带来的额外搜索深度
        self._last_visual_hashes = None
        self.pending_jieqi_analysis_retry = False
        self.jieqi_analysis_retry_count = 0
        self._pending_lift_source = None
        
        # 优化：模拟状态缓存
        self._sim_cache = {
            'base_fen': None,
            'moves_str': None, 
            'board': None # 上一次推演出的fen
        }
        
        # 备份状态 (用于 Undo)
        self._backup_last_board = None
        self._backup_last_counts = None 
        
    def reset(self):
        """重置检查器状态，用于手动刷新时清除历史状态"""
        self.last_board = None
        self.last_counts = None
        self.red_start_count = 0
        self.consecutive_drops = 0
        self.consecutive_mismatches = 0
        self.in_settlement_screen = False  # 重置结算状态
        self.capture_depth_bonus = 0
        self._last_visual_hashes = None
        self.pending_jieqi_analysis_retry = False
        self.jieqi_analysis_retry_count = 0
        self._pending_lift_source = None
        
        # 清空备份
        self._backup_last_board = None 
        self._backup_last_counts = None

        # 清空缓存
        self._sim_cache = { 'base_fen': None, 'moves_str': None, 'board': None }

    @property
    def start_red(self):
        return self.START_JIEQI_RED if self.variant == "jieqi" else self.START_RED

    @property
    def start_black(self):
        return self.START_JIEQI_BLACK if self.variant == "jieqi" else self.START_BLACK

    @property
    def start_counts(self):
        return self.JIEQI_COUNTS.copy() if self.variant == "jieqi" else self.START_COUNTS.copy()

    def normalize_visual_board(
        self, board_array, grid_hashes=None, marker_coords=None, details=None
    ):
        """把揭棋画面的未翻棋子稳定表示为X/x。

        棋子模型不需要新增15种暗子类别：开局由标准暗子阵形建立状态，
        后续未移动暗子沿用X/x；暗子一旦移动，目标格的CNN结果就是其
        揭示后的真实身份。
        """
        if self.variant != "jieqi" or board_array is None:
            return board_array

        board = [row[:] for row in board_array]
        raw_board = [row[:] for row in board_array]
        if self.last_board is None:
            # 只要将帅方向明确，就从完整揭棋开局建立暗子状态。揭棋模式
            # 必须从新局开始跟踪，避免对中途局面凭空补暗子。
            has_black_top = any(board[r][c] == 'k' for r in range(3) for c in range(3, 6))
            has_red_top = any(board[r][c] == 'K' for r in range(3) for c in range(3, 6))
            if has_black_top != has_red_top:
                template = self.START_JIEQI_RED if has_black_top else self.START_JIEQI_BLACK
                self._last_visual_hashes = grid_hashes
                return [row[:] for row in template]
            self._last_visual_hashes = grid_hashes
            return board

        previous_hashes = self._last_visual_hashes
        changed_hashes = set()
        if grid_hashes is not None and previous_hashes is not None:
            for r in range(min(10, len(grid_hashes), len(previous_hashes))):
                for c in range(min(9, len(grid_hashes[r]), len(previous_hashes[r]))):
                    if grid_hashes[r][c] != previous_hashes[r][c]:
                        changed_hashes.add((r, c))

        for r in range(10):
            for c in range(9):
                previous = self.last_board[r][c]
                current = board[r][c]
                unchanged = bool(
                    grid_hashes is not None
                    and previous_hashes is not None
                    and r < len(grid_hashes)
                    and r < len(previous_hashes)
                    and c < len(grid_hashes[r])
                    and c < len(previous_hashes[r])
                    and grid_hashes[r][c] == previous_hashes[r][c]
                )
                # 软刷新会清空识别器自己的缓存，但Checker仍保存最后可信帧。
                # 图像哈希未变化的格子直接沿用可信结果，避免一次低置信度
                # 把大量已揭棋子误清为空格。
                if unchanged:
                    board[r][c] = previous
                    continue
                if previous not in ('X', 'x'):
                    continue
                # 同色的任意CNN类别都是暗子背面的误分类，继续保持暗子；
                # 空格表示它已离开，异色棋子表示它已被吃并被对方占据。
                if current != '-' and current.isupper() == previous.isupper():
                    board[r][c] = previous

        # 暗子移动后，落点会显示真实棋种，但起点的空格有时仍会被CNN误判
        # 为同色棋子，上面的暗子保护便会让画面只剩一个格子变化。此时结合
        # 移动光圈、格子哈希变化和暗子名义棋种规则，恢复唯一可信的起点。
        marker_set = set(marker_coords or [])
        low_confidence_predictions = {}
        for detail in details or []:
            error_type = getattr(getattr(detail, 'type', None), 'name', '')
            if error_type != 'LOW_CONFIDENCE':
                continue
            position = getattr(detail, 'position', None)
            piece_type = getattr(detail, 'piece_type', None)
            confidence = float(getattr(detail, 'confidence', 0.0) or 0.0)
            if position is not None and piece_type:
                low_confidence_predictions[tuple(position)] = (
                    piece_type,
                    confidence,
                )
        for dst_r in range(10):
            for dst_c in range(9):
                revealed = board[dst_r][dst_c]
                old_target = self.last_board[dst_r][dst_c]
                if (
                    revealed in ('-', 'X', 'x', 'K', 'k')
                    or revealed == old_target
                    or (old_target != '-' and old_target.isupper() == revealed.isupper())
                ):
                    continue

                candidates = []
                for src_r in range(10):
                    for src_c in range(9):
                        dark = self.last_board[src_r][src_c]
                        if dark not in ('X', 'x') or dark.isupper() != revealed.isupper():
                            continue
                        if (src_r, src_c) == (dst_r, dst_c):
                            continue

                        step_info = {
                            'from_pos': (src_r, src_c),
                            'to_pos': (dst_r, dst_c),
                            'piece': dark,
                        }
                        if not self.is_step_legal(
                            self.last_board, board, self.is_red, step_info
                        ):
                            continue

                        source = (src_r, src_c)
                        marker_evidence = source in marker_set
                        hash_evidence = source in changed_hashes
                        visual_evidence = raw_board[src_r][src_c] != dark
                        if marker_evidence or hash_evidence:
                            candidates.append((
                                marker_evidence,
                                hash_evidence,
                                visual_evidence,
                                source,
                            ))

                if not candidates:
                    continue

                # 标记优先，其次使用哈希和原始分类变化。只有最高证据候选唯一
                # 时才纠正，避免在多个暗子都可能到达时猜错并污染历史。
                candidates.sort(reverse=True)
                best_score = candidates[0][:3]
                best = [item for item in candidates if item[:3] == best_score]
                if len(best) != 1:
                    continue

                src_r, src_c = best[0][3]
                board[src_r][src_c] = '-'
                logger.info(
                    f"揭棋补全暗子移动: 起点={(src_r, src_c)}, "
                    f"落点={(dst_r, dst_c)}, 揭示={revealed}, "
                    f"标记={best[0][0]}, 哈希变化={best[0][1]}"
                )
                # 一帧最多只补全一步棋。
                self._last_visual_hashes = grid_hashes
                return board

        # 已揭棋子移动时，选中光圈可能令起点或落点的CNN置信度降低。
        # Recognizer会安全回退到上一帧，因此表面上只剩一个端点变化。
        # 结合低置信度(None哈希)、光圈、哈希变化及走法规则补全另一端，
        # 让这种明确变化在第一张稳定帧就通过，而不是等待三轮重拍。
        changes = [
            (r, c, self.last_board[r][c], board[r][c])
            for r in range(10)
            for c in range(9)
            if self.last_board[r][c] != board[r][c]
        ]

        def has_none_hash(pos):
            if grid_hashes is None:
                return False
            r, c = pos
            return (
                r < len(grid_hashes)
                and c < len(grid_hashes[r])
                and grid_hashes[r][c] is None
            )

        def select_unique(candidates):
            if not candidates:
                return None
            candidates.sort(reverse=True)
            best_score = candidates[0][:-1]
            best = [item for item in candidates if item[:-1] == best_score]
            return best[0][-1] if len(best) == 1 else None

        if len(changes) == 1:
            row, col, old_piece, new_piece = changes[0]

            # 起点已经变空，但落点因光圈低置信度仍被回退为空格。
            if old_piece not in ('-', 'X', 'x') and new_piece == '-':
                src = (row, col)
                candidates = []
                for dst_r in range(10):
                    for dst_c in range(9):
                        dst = (dst_r, dst_c)
                        target = self.last_board[dst_r][dst_c]
                        if dst == src or (
                            target != '-'
                            and target.isupper() == old_piece.isupper()
                        ):
                            continue
                        marker_evidence = dst in marker_set
                        prediction = low_confidence_predictions.get(dst)
                        low_confidence = bool(
                            has_none_hash(dst)
                            and prediction
                            and prediction[0] == old_piece
                            and prediction[1] >= 0.25
                        )
                        hash_evidence = dst in changed_hashes
                        visual_evidence = raw_board[dst_r][dst_c] != target
                        # 落点必须有“确实看见同一棋子”的正证据。单纯哈希
                        # 改变可能只是鼠标、光圈或悬空棋子的动画，不能据此
                        # 猜一个落点。
                        if not (marker_evidence or low_confidence or visual_evidence):
                            continue
                        step_info = {
                            'from_pos': src,
                            'to_pos': dst,
                            'piece': old_piece,
                        }
                        if self.is_step_legal(
                            self.last_board, board, self.is_red, step_info
                        ):
                            candidates.append((
                                marker_evidence,
                                low_confidence,
                                hash_evidence,
                                visual_evidence,
                                dst,
                            ))

                dst = select_unique(candidates)
                if dst is not None:
                    board[dst[0]][dst[1]] = old_piece
                    logger.info(
                        f"揭棋补全已揭棋子落点: 起点={src}, 落点={dst}, "
                        f"棋子={old_piece}"
                    )

            # 落点已识别，但起点因低置信度仍保留着上一帧棋子。
            elif (
                new_piece not in ('-', 'X', 'x')
                and new_piece != old_piece
                and (
                    old_piece == '-'
                    or old_piece.isupper() != new_piece.isupper()
                )
            ):
                dst = (row, col)
                candidates = []
                for src_r in range(10):
                    for src_c in range(9):
                        src = (src_r, src_c)
                        if src == dst or self.last_board[src_r][src_c] != new_piece:
                            continue
                        marker_evidence = src in marker_set
                        prediction = low_confidence_predictions.get(src)
                        low_confidence = bool(
                            has_none_hash(src)
                            and prediction
                            and prediction[0] in ('-', '.')
                            and prediction[1] >= 0.25
                        )
                        hash_evidence = src in changed_hashes
                        visual_evidence = (
                            raw_board[src_r][src_c]
                            != self.last_board[src_r][src_c]
                        )
                        # 起点也必须有空格/移动标记的正证据，不能因为动画
                        # 引起的哈希变化就删除一枚仍被抬在空中的棋子。
                        if not (marker_evidence or low_confidence or visual_evidence):
                            continue
                        step_info = {
                            'from_pos': src,
                            'to_pos': dst,
                            'piece': new_piece,
                        }
                        if self.is_step_legal(
                            self.last_board, board, self.is_red, step_info
                        ):
                            candidates.append((
                                marker_evidence,
                                low_confidence,
                                hash_evidence,
                                visual_evidence,
                                src,
                            ))

                src = select_unique(candidates)
                if src is not None:
                    board[src[0]][src[1]] = '-'
                    logger.info(
                        f"揭棋补全已揭棋子起点: 起点={src}, 落点={dst}, "
                        f"棋子={new_piece}"
                    )

        self._last_visual_hashes = grid_hashes
        return board

    def reset_capture_depth_bonus(self):
        self.capture_depth_bonus = 0

    def record_own_piece_captured(self, captured_piece):
        """记录一次经过合法走子校验的我方损子。"""
        if not captured_piece or captured_piece == '-':
            return False
        captured_is_red = captured_piece.isupper()
        if captured_is_red != bool(self.is_red):
            return False
        self.capture_depth_bonus += 1
        logger.info(
            f"我方棋子被吃: {captured_piece}, 动态深度加成={self.capture_depth_bonus}"
        )
        return True
    
    def check_settlement(self, board_array, is_massive_change):
        """
        检测是否为结算画面
        Args:
            board_array: 棋盘数组（可为 None，表示识别失败）
            is_massive_change: 是否检测到巨大变化
        Returns:
            bool: True 表示是结算画面，需要发送 NON_GAME_SCREEN 消息
        """
        # 识别失败时，如果已在结算状态，保持结算状态
        if board_array is None:
            if self.in_settlement_screen:
                logger.debug("识别失败，保持结算画面状态")
                return True
            return False
        
        # 快速路径：既没有巨大变化，也不在结算状态，无需检测
        if not is_massive_change and not self.in_settlement_screen:
            return False
        
        # 需要检测时才统计将帅数量
        king_count = sum(1 for row in board_array for piece in row if piece == 'k')
        general_count = sum(1 for row in board_array for piece in row if piece == 'K')
        kings_missing = (king_count != 1 or general_count != 1)
        
        if kings_missing:
            # 将帅丢失
            if is_massive_change:
                # 巨大变化 + 将帅丢失 = 进入结算状态
                self.in_settlement_screen = True
                logger.debug(f"进入结算画面 (巨大变化 + 将{king_count}个/帅{general_count}个)")
            
            if self.in_settlement_screen:
                # 已在结算状态
                logger.debug("保持结算画面状态")
                self.consecutive_drops = 0  # 重置丢帧计数
                return True
        else:
            # 将帅存在
            if self.in_settlement_screen:
                # 从结算状态恢复（新对局开始）
                logger.debug("将帅恢复，退出结算状态")
                self.in_settlement_screen = False
            
            if is_massive_change:
                # 巨大变化 + 将帅存在 = 可能是新对局
                logger.debug("检测到巨大变化但将帅存在，可能是新对局")
        
        return False

    def force_sync_board(self, board_array):
        """强制同步棋盘状态（用于处理连续非法帧导致的卡死）"""
        self.last_board = [row[:] for row in board_array]
        # 获取当前棋子数量统计（忽略合法性检查结果，只取计数）
        _, _, self.last_counts = self.check_pieces_count(board_array)
        self.consecutive_drops = 0
        self._sim_cache = { 'base_fen': None, 'moves_str': None, 'board': None }
        logger.debug("检查器状态已重置 (Force Sync)")

    def update_side_detection(self, board_array):
        """
        更新红黑方判断 (Latch Logic / 状态保持)
        仅当明确检测到上方将帅时才更新状态，避免因检测失败导致的误判
        """
        # 扫描上方九宫格 (前3行, 中间3列)
        has_black_king = False
        has_red_king = False
        
        for r in range(3):
            for c in range(3, 6):
                if board_array[r][c] == 'k':
                    has_black_king = True
                elif board_array[r][c] == 'K':
                    has_red_king = True
        
        # 状态更新逻辑
        if has_black_king and not has_red_king:
            if not self.is_red:
                logger.info("Side Detection: Detected Black King at top -> I am RED")
            self.is_red = True
        elif has_red_king and not has_black_king:
            if self.is_red:
                logger.info("Side Detection: Detected Red King at top -> I am BLACK")
            self.is_red = False
        # else: 如果都没检测到，或都检测到了(异常)，保持 is_red 不变

    def is_position_valid(self, piece_type, x, y, is_red_at_bottom):
        """
        根据中国象棋规则验证(x,y)是否为 "兵卒 象相 士仕 将帅" 的合法位置
        Args:
            piece_type: 棋子类型
            x: 棋盘横坐标
            y: 棋盘纵坐标
            is_red_at_bottom: 红方在棋盘底部
        Returns:
            bool: 位置是否合法
        """
    
        if piece_type in ('X', 'x'):
            return self.variant == "jieqi"
        is_red_piece = piece_type.isupper()
        
        # 士/仕
        if piece_type.lower() == 'a':
            palace_coords = [(3, 7), (5, 7), (4, 8), (3, 9), (5, 9)] if is_red_at_bottom else [(3, 0), (5, 0), (4, 1), (3, 2), (5, 2)]
            if not is_red_piece: # 如果是黑方，则使用对面的宫殿坐标
                palace_coords = [(3, 0), (5, 0), (4, 1), (3, 2), (5, 2)] if is_red_at_bottom else [(3, 7), (5, 7), (4, 8), (3, 9), (5, 9)]
            return (x, y) in palace_coords
        
        # 相/象
        elif piece_type.lower() == 'b':
            own_side_coords = [(2, 5), (6, 5), (0, 7), (4, 7), (8, 7), (2, 9), (6, 9)] if is_red_at_bottom else [(2, 0), (6, 0), (0, 2), (4, 2), (8, 2), (2, 4), (6, 4)]
            if not is_red_piece:
                own_side_coords = [(2, 0), (6, 0), (0, 2), (4, 2), (8, 2), (2, 4), (6, 4)] if is_red_at_bottom else [(2, 5), (6, 5), (0, 7), (4, 7), (8, 7), (2, 9), (6, 9)]
            return (x, y) in own_side_coords
        
        # 将/帅
        elif piece_type.lower() == 'k':
            palace_coords = [(3, 7), (4, 7), (5, 7), (3, 8), (4, 8), (5, 8), (3, 9), (4, 9), (5, 9)] if is_red_at_bottom else [(3, 0), (4, 0), (5, 0), (3, 1), (4, 1), (5, 1), (3, 2), (4, 2), (5, 2)]
            if not is_red_piece:
                palace_coords = [(3, 0), (4, 0), (5, 0), (3, 1), (4, 1), (5, 1), (3, 2), (4, 2), (5, 2)] if is_red_at_bottom else [(3, 7), (4, 7), (5, 7), (3, 8), (4, 8), (5, 8), (3, 9), (4, 9), (5, 9)]
            return (x, y) in palace_coords
        
        # 兵/卒
        elif piece_type.lower() == 'p':
            if is_red_piece:
                y_limit, y_start = (5, 6) if is_red_at_bottom else (4, 3)
                if (is_red_at_bottom and y >= y_limit) or (not is_red_at_bottom and y <= y_limit):
                    return y in [y_start, y_limit] and x in [0, 2, 4, 6, 8]
            else: # Black piece
                y_limit, y_start = (4, 3) if is_red_at_bottom else (5, 6)
                if (is_red_at_bottom and y <= y_limit) or (not is_red_at_bottom and y >= y_limit):
                    return y in [y_start, y_limit] and x in [0, 2, 4, 6, 8]
            return True
    
        return True

    def check_pieces_count(self, array):
        """
        检查棋子数量是否合法
        1. 先检查绝对上限（如马最多2个），超限返回非法
        2. 再检查相对变化（比上一帧增多视为重置）
        
        Args:
            array: 棋盘数组
        """
        counts = {}
        for row in array:
            for piece in row:
                if piece != '-':
                    counts[piece] = counts.get(piece, 0) + 1
        
        # 1. 检查绝对上限（中国象棋规则：各棋子的初始数量）
        # 任何棋子数量超过初始数量都是非法的（不可能通过正常走棋产生）
        for piece, count in counts.items():
            max_count = (self.JIEQI_COUNTS if self.variant == "jieqi" else self.START_COUNTS).get(piece, 0)
            if count > max_count:
                piece_names = {
                    'r': '黑车', 'n': '黑马', 'b': '黑象', 'a': '黑士', 'k': '黑将', 'c': '黑炮', 'p': '黑卒',
                    'R': '红车', 'N': '红马', 'B': '红相', 'A': '红士', 'K': '红帅', 'C': '红炮', 'P': '红兵'
                }
                name = piece_names.get(piece, piece)
                return False, f"非法棋子数量: {name}{count}个 (上限{max_count})", counts
        
        # 2. 检查将帅是否都存在
        king_count = counts.get('k', 0)
        general_count = counts.get('K', 0)
        if king_count != 1 or general_count != 1:
            return False, f"非法将帅数量: 检测到{king_count}个将,{general_count}个帅", counts
        
        # 3. 首次初始化时，直接返回成功
        if self.last_counts is None:
            return True, "重置局面", counts
        
        # 4. 检查相对变化（比上一帧增多）
        for piece, count in counts.items():
            if piece.lower() == 'k':
                continue
            if count > self.last_counts.get(piece, 0):
                if self.variant == "jieqi" and piece not in ('X', 'x'):
                    # 暗子揭开后，真实棋种数量从0增加是正常变化。
                    continue
                # 棋子数量变多是不可能的（除非是新对局/悔棋/上一帧识别错了）
                # 但仅凭此无法判断局面是否合法，因为可能没有超出棋子数量上限
                # 为了避免死锁（上一帧识别少了个子，这一帧恢复了，结果一直报非法），这里视为"多步变化/重置"
                return True, f"棋子{piece}数量增加（{self.last_counts.get(piece, 0)}->{count}），视为重置", counts
        
        return True, "棋子数量合理", counts

    def check_pieces_position(self, array, is_red_at_bottom):
        """
        检查棋子位置是否符合规则
        返回: (是否合理, 错误信息)
        """                
        # 检查所有棋子位置
        for i in range(len(array)):
            for j in range(len(array[i])):
                piece = array[i][j]
                if piece != '-':
                    # 揭棋中揭开的士可离宫、象可过河，其他随机棋种也会
                    # 出现在普通象棋不可能出现的初始位置；这里只继续约束将帅。
                    if self.variant == "jieqi" and piece.lower() != 'k':
                        continue
                    if not self.is_position_valid(piece, j, i, is_red_at_bottom):
                        return False, f"棋子{piece}在位置({i},{j})不合法"
        return True, "棋子位置合理"
    
    # 检查两个局面之间的移动是否合法
    def is_step_legal(self, a1, a2, is_red_at_bottom, step_info=None):
        ROWS, COLS = 10, 9

        def find_move():
            changes = []
            for r in range(ROWS):
                for c in range(COLS):
                    if a1[r][c] != a2[r][c]:
                        changes.append(((r, c), a1[r][c], a2[r][c]))

            if len(changes) != 2:
                return None, None

            change1, change2 = changes
            pos1, old1, new1 = change1
            pos2, old2, new2 = change2

            # Standard move: piece -> empty, empty -> piece
            if new1 == '-' and old2 == '-':
                if old1 == new2: return pos1, pos2
            if new2 == '-' and old1 == '-':
                if old2 == new1: return pos2, pos1

            # Capture move: piece -> empty, captured_piece -> piece
            if new1 == '-' and old2 != '-':
                if old1 == new2: return pos1, pos2
            if new2 == '-' and old1 != '-':
                if old2 == new1: return pos2, pos1
            
            return None, None

        def same_side(p1, p2): return p1 != '-' and p2 != '-' and (p1.isupper() == p2.isupper())

        def count_pieces_between(r1, c1, r2, c2):
            count = 0
            if r1 == r2:
                step = 1 if c1 < c2 else -1
                for c in range(c1 + step, c2, step):
                    if a1[r1][c] != '-': count += 1
            elif c1 == c2:
                step = 1 if r1 < r2 else -1
                for r in range(r1 + step, r2, step):
                    if a1[r][c1] != '-': count += 1
            return count

        def is_legal_rook(r1, c1, r2, c2):
            return (r1 == r2 or c1 == c2) and count_pieces_between(r1, c1, r2, c2) == 0

        def is_legal_cannon(r1, c1, r2, c2, is_capture):
            if r1 != r2 and c1 != c2: return False
            pieces_between = count_pieces_between(r1, c1, r2, c2)
            return (is_capture and pieces_between == 1) or (not is_capture and pieces_between == 0)

        def is_legal_knight(r1, c1, r2, c2):
            dr, dc = r2 - r1, c2 - c1
            if (abs(dr), abs(dc)) not in [(2, 1), (1, 2)]: return False
            hobble_r = r1 + dr // 2 if abs(dr) == 2 else r1
            hobble_c = c1 + (c2-c1) // 2 if abs(dc) == 2 else c1
            return a1[hobble_r][hobble_c] == '-'

        def is_legal_bishop(r1, c1, r2, c2, is_red_piece):
            if abs(r1 - r2) != 2 or abs(c1 - c2) != 2: return False
            eye_r, eye_c = (r1 + r2) // 2, (c1 + c2) // 2
            if a1[eye_r][eye_c] != '-': return False
            if self.variant == "jieqi":
                return True
            if is_red_piece:
                return r2 >= 5 if is_red_at_bottom else r2 <= 4
            else:
                return r2 <= 4 if is_red_at_bottom else r2 >= 5

        def is_legal_advisor(r1, c1, r2, c2, is_red_piece):
            if abs(r1 - r2) != 1 or abs(c1 - c2) != 1: return False
            if self.variant == "jieqi":
                return True
            if not (3 <= c2 <= 5): return False
            if is_red_piece:
                return r2 >= 7 if is_red_at_bottom else r2 <= 2
            else:
                return r2 <= 2 if is_red_at_bottom else r2 >= 7

        def is_legal_king(r1, c1, r2, c2, is_red_piece):
            if abs(r1 - r2) + abs(c1 - c2) != 1: return False
            if not (3 <= c2 <= 5): return False
            if is_red_piece:
                return r2 >= 7 if is_red_at_bottom else r2 <= 2
            else:
                return r2 <= 2 if is_red_at_bottom else r2 >= 7

        def is_legal_pawn(r1, c1, r2, c2, is_red_piece):
            dr, dc = r2 - r1, abs(c2 - c1)
            if abs(dr) + dc != 1: return False
            
            forward_dr = -1 if is_red_at_bottom else 1
            if is_red_piece:
                river_crossed = r1 <= 4 if is_red_at_bottom else r1 >= 5
                if dr != forward_dr and not river_crossed: return False
                if dr != forward_dr and dc == 0: return False
                return True
            else: # black piece
                river_crossed = r1 >= 5 if is_red_at_bottom else r1 <= 4
                if dr != -forward_dr and not river_crossed: return False
                if dr != -forward_dr and dc == 0: return False
                return True

        def is_facing_kings(board):
            red_k, black_k = None, None
            for r in range(ROWS):
                for c in range(COLS):
                    p = board[r][c]
                    if p == 'K': red_k = (r, c)
                    if p == 'k': black_k = (r, c)
            if not (red_k and black_k and red_k[1] == black_k[1]): return False
            return count_pieces_between(red_k[0], red_k[1], black_k[0], black_k[1]) == 0

        # --- Main Logic ---
        if step_info:
            src, dst, piece = step_info['from_pos'], step_info['to_pos'], step_info['piece']
        else:
            src, dst = find_move()
            if not src or not dst: return False
            piece = a1[src[0]][src[1]]

        target = a1[dst[0]][dst[1]]

        if piece == '-' or same_side(piece, target): return False

        is_red_piece = piece.isupper()
        if self.variant == "jieqi" and piece in ('X', 'x'):
            # 暗子首次移动按其开局位置的名义棋种行棋，落地后才揭示
            # 随机的真实身份。
            nominal_board = self.START_RED if is_red_at_bottom else self.START_BLACK
            piece = nominal_board[src[0]][src[1]]
            if piece == '-':
                return False
        kind = piece.upper()
        ok = False

        if kind == 'R': ok = is_legal_rook(src[0], src[1], dst[0], dst[1])
        elif kind == 'C': ok = is_legal_cannon(src[0], src[1], dst[0], dst[1], target != '-')
        elif kind == 'N': ok = is_legal_knight(src[0], src[1], dst[0], dst[1])
        elif kind == 'B': ok = is_legal_bishop(src[0], src[1], dst[0], dst[1], is_red_piece)
        elif kind == 'A': ok = is_legal_advisor(src[0], src[1], dst[0], dst[1], is_red_piece)
        elif kind == 'K': ok = is_legal_king(src[0], src[1], dst[0], dst[1], is_red_piece)
        elif kind == 'P': ok = is_legal_pawn(src[0], src[1], dst[0], dst[1], is_red_piece)

        if not ok: return False
        
        # Check if king is in check after move
        new_board = [row[:] for row in a1]
        new_board[dst[0]][dst[1]] = new_board[src[0]][src[1]]
        new_board[src[0]][src[1]] = '-'
        if is_facing_kings(new_board): return False
        
        return True

    def check_position_changes(self, a1, a2, is_red_at_bottom):
        """
        分析两个局面之间的变化
        Args:
            a1: 上个局面数组
            a2: 当前局面数组
            is_red_at_bottom: 红方在棋盘底部
        Returns:
            BoardStatus: 变化分析结果
        """
        changed_positions = []
        red_start = True
        black_start = True
        for i in range(len(a1)):
            for j in range(len(a1[i])):
                if a1[i][j] != a2[i][j]:
                    changed_positions.append((i, j, a1[i][j], a2[i][j]))
                if red_start and a2[i][j] != self.start_red[i][j]:
                    red_start = False
                if black_start and a2[i][j] != self.start_black[i][j]:
                    black_start = False
        if red_start:
            return BoardStatus(is_red_start=True, is_new_game=True, message="红方开局")
        if black_start:
            return BoardStatus(is_black_start=True, is_new_game=True, message="黑方开局")
        
        if len(changed_positions) == 0:
            return BoardStatus(is_same_board=True, message="局面无变化")

        # 有2处格子变化
        if len(changed_positions) == 2:
            src = dst = None
            moving_piece = captured_piece = None
            
            for row, col, old_piece, new_piece in changed_positions:
                if old_piece != '-' and new_piece == '-':
                    # 起始位置（棋子离开的位置）
                    src = (row, col)
                    moving_piece = old_piece
                elif old_piece == '-' and new_piece != '-':
                    # 目标位置（棋子到达的位置）
                    dst = (row, col)
                elif old_piece != '-' and new_piece != '-':
                    # 吃子情况：被吃的棋子和移动的棋子颜色不同
                    if old_piece.isupper() != new_piece.isupper():
                        captured_piece = old_piece
                        dst = (row, col)

            # 检查解析结果
            if not src or not dst:
                return BoardStatus(is_illegal_change=True, message='非法变化：无法解析为单步移动')

            # 检查移动合法性
            step_info = {
                'from_pos': src, 
                'to_pos': dst, 
                'piece': moving_piece,
                'side': 'red' if moving_piece.isupper() else 'black',
                'captured_piece': captured_piece,
                'revealed_piece': a2[dst[0]][dst[1]] if moving_piece in ('X', 'x') else None,
            }
            is_legal = self.is_step_legal(a1, a2, is_red_at_bottom, step_info)
            
            if not is_legal:
                return BoardStatus(is_illegal_change=True, message='非法的移动')

            # 判断移动归属
            side_of_move = step_info.get('side')
            is_my_step = (is_red_at_bottom and side_of_move == 'red') or \
                         (not is_red_at_bottom and side_of_move == 'black')
            
            return BoardStatus(
                is_my_step=is_my_step,
                is_opponent_step=not is_my_step,
                step_info=step_info,
                message='我方单步合法的移动' if is_my_step else '对方单步合法的移动'
            )

        # 多步移动，包含所有变化信息
        if len(changed_positions) > 2:
            step_info = {}
            for idx, (row, col, old_piece, new_piece) in enumerate(changed_positions, 1):
                step_info[f'change{idx}'] = ((row, col), (old_piece, new_piece))
            return BoardStatus(
                is_multi_step=True, 
                step_info=step_info, 
                message='检测到多步变化'
            )

        # 只有一个格子变化
        if len(changed_positions) == 1:
            row, col, old_piece, new_piece = changed_positions[0]
            is_lifted = old_piece != '-' and new_piece == '-'
            return BoardStatus(
                is_illegal_change=True,
                step_info={
                    'transient_single_change': True,
                    'is_lifted_piece': is_lifted,
                    'position': (row, col),
                    'piece': old_piece if is_lifted else new_piece,
                },
                message=(
                    '检测到棋子抬起，等待落子'
                    if is_lifted else
                    '检测到不完整走子，等待另一端稳定'
                ),
            )
        
        # 默认返回多步移动
        return BoardStatus(is_illegal_change=True, message='非法或未知局面')

    def check_board(self, current_board, marker_coords=None, base_fen=None, history_moves=None):
        """
        检查当前局面是否合法
        Args:
            current_board: 当前局面数组
            marker_coords: 标记坐标列表 (可选)
            base_fen: 历史基准FEN (可选)
            history_moves: 历史着法字符串 (可选)
        Returns:
            BoardStatus: 检查结果
        """
        
        if current_board is None:
            return None
        
        self.update_side_detection(current_board)

        # 首次初始化
        if self.last_board is None:
            self.last_board = [row[:] for row in (self.start_red if self.is_red else self.start_black)]
            self.last_counts = self.start_counts
            # 注意: 这里无法初始化 last_grid_hashes，因为是硬编码的局面，没有图片哈希
            # 但不影响，后续第一次识别时会全是 cache miss，从而全量识别
        
        # 0. 全面分析局面变化
        result = self.check_position_changes(self.last_board, current_board, self.is_red)
        
        # 在应用任何更新前，先备份当前状态
        self._backup_last_board = [row[:] for row in self.last_board]
        self._backup_last_counts = self.last_counts.copy() if self.last_counts else None
        
        # 1. 检测初始局面
        if result.is_red_start:
            if self.red_start_count < 1: # 开局帧最大允许连续出现次数(决定开局时会显示几次开局走法)
                # 允许前两次返回红方开局
                self.red_start_count += 1
                self.last_board = [row[:] for row in self.start_red]
                self.last_counts = self.start_counts
                return result
            else:
                # 超过1次则视为相同画面
                return BoardStatus(is_same_board=True, message="红方开局（>1次）相同画面")
        if result.is_black_start:
            self.last_board = [row[:] for row in self.start_black]
            self.last_counts = self.start_counts
            return result
        
        # 2. 检测相同局面 (最高频情形)
        if result.is_same_board:
            return result
        
        # 3. 核心逻辑：先通过棋盘变化推断走棋，标记仅作为辅助验证
        # （新设计：视觉棋盘为真相源，标记为辅助验证）
        if result.is_my_step or result.is_opponent_step:
            # 3.1 棋盘变化已成功推断出走棋
            inferred_side = result.step_info.get('side')  # 'red' or 'black'
            inferred_is_my_step = result.is_my_step
            
            # 3.2 如果有标记，用标记验证推断结果
            if self.last_board and marker_coords:
                marker_side = self._infer_side_from_marker(marker_coords, current_board)
                
                if marker_side is not None:
                    # 标记存在且可解析
                    marker_is_my_step = (self.is_red and marker_side == 'red') or \
                                        (not self.is_red and marker_side == 'black')
                    
                    if marker_is_my_step != inferred_is_my_step:
                        # 标记与推断不一致，视为非法帧（可能是动画过渡帧）
                        logger.debug(f"标记验证失败: 推断={inferred_side}, 标记={marker_side}")
                        return BoardStatus(
                            is_illegal_change=True, 
                            message=f"标记验证失败: 推断为{inferred_side}走棋，但标记指示{marker_side}"
                        )
                    else:
                        # 标记与推断一致，增强可信度
                        result.message += " (标记验证通过)"
                # 标记无法解析时（marker_side is None），继续使用推断结果
            
            # 3.3 历史校验 (在更新状态之前！)
            # Verify First: 只有通过历史校验，才认为这步棋是安全的，允许更新内部状态
            self._verify_history_consistency(result, current_board, base_fen, history_moves)
            
            if result.is_history_mismatch:
                # 校验失败：拒绝更新 last_board
                # 这会导致下一帧检测到"Persistent Change" (持续变化)，
                # 从而产生连续的 Update Rejection (Drop Frame)，触发 Processor 的 Force Reset
                logger.debug("历史校验失败，拒绝更新 checker 状态")
                return result

            # 3.4 更新状态（仅当校验通过时）
            self.last_board = [row[:] for row in current_board]
            _, _, self.last_counts = self.check_pieces_count(current_board)
            self.red_start_count = 0
            
            return result
        
        # 4. 过滤其他非法局面
        count_valid, count_msg, current_counts = self.check_pieces_count(current_board)
        if not count_valid:
            return BoardStatus(is_illegal_board=True, message=count_msg)
        
        if "重置" in count_msg:
             return BoardStatus(is_multi_step=True, step_info={}, message=count_msg)
        
        position_valid, position_msg = self.check_pieces_position(current_board, self.is_red)
        if not position_valid:
            return BoardStatus(is_illegal_board=True, message=position_msg)
        
        # 5. 多步移动或残局
        if result.is_multi_step:
            # [unified] 拒绝立即更新，交由 Processor 防抖确认 (Unified Anomaly Handling)
            # 只有当连续几帧都检测到 Multi-Step (Drop Frame) 时，Processor 才会触发 Force Sync
            return result
        
        return result
    
    def _infer_side_from_marker(self, marker_coords, current_board):
        """
        辅助方法：从标记位置推断走棋方
        通过检查标记位置在上一帧是否有棋子离开来判断
        
        Returns:
            'red' | 'black' | None (无法判断)
        """
        for r, c in marker_coords:
            if not (0 <= r < len(self.last_board) and 0 <= c < len(self.last_board[0])):
                continue
            piece_last = self.last_board[r][c]
            piece_curr = current_board[r][c]
            
            # 找到棋子离开的位置（起点）
            if piece_last != '-' and piece_curr == '-':
                return 'red' if piece_last.isupper() else 'black'
        
        return None  # 无法从标记判断

    def _verify_history_consistency(self, result, current_board, base_fen, history_moves):
        """
        辅助方法：校验历史一致性 (In-Place Modification)
        """
        if result.is_my_step or result.is_opponent_step:
            # 1. 提取本次移动
            step_info = result.step_info
            if not step_info:
                return

            from app.tools import utils
            move_str = utils.convert_coords_to_move(
                step_info.get('from_pos'),
                step_info.get('to_pos'),
                self.is_red
            )
            if self.variant == "jieqi" and step_info.get('piece') in ('X', 'x'):
                revealed = step_info.get('revealed_piece')
                if revealed and revealed not in ('-', 'X', 'x'):
                    move_str += revealed
            
            # --- 增量模拟核心逻辑 ---
            from app.chess.simulation import ChessSimulation
            
            sim_board = None
            
            # A. 尝试使用/更新缓存
            cache = self._sim_cache
            
            # 规范化 base_fen & history (防止 None), 并检查 cache['board'] 是否存在
            norm_base_fen = base_fen if base_fen else 'startpos'
            norm_cache_fen = cache['base_fen'] if cache['base_fen'] else 'startpos'
            norm_history = history_moves if history_moves else ""
            cached_moves = cache['moves_str'] if cache['moves_str'] else ""

            # 只有当:
            # 1. 缓存中有有效的 board 对象 (关键! 防止初次进入迭代 None)
            # 2. base_fen 一致 (处理 None/startpos 等价)
            # 3. history_moves 是 cache 的延续
            if cache['board'] and \
               norm_cache_fen == norm_base_fen and \
               norm_history.startswith(cached_moves):
                
                # 缓存命中：计算增量部分
                cached_len = len(cached_moves)
                new_part = norm_history[cached_len:].strip()
                
                logger.debug(f"History Cache Hit! Incremental: '{new_part}' (Base: {len(cache['moves_str'] if cache['moves_str'] else '')} chars)")

                sim_board = [row[:] for row in cache['board']] # 复制一份缓存作为起点
                
                if new_part:
                    for mv in new_part.split():
                        ChessSimulation.apply_uci_move(sim_board, mv)
                    
                    # 这样下一次校验就能基于这个新起点
                    cache['moves_str'] = norm_history
                    cache['board'] = [row[:] for row in sim_board]
            

            # B. 缓存失效，全量重算
            if sim_board is None:
                if norm_base_fen == 'startpos':
                    sim_board = [row[:] for row in (
                        self.START_JIEQI_RED
                        if self.variant == "jieqi"
                        else ChessSimulation.START_RED_BOTTOM
                    )]
                    move_list = history_moves.split() if history_moves else []
                    for mv in move_list:
                         ChessSimulation.apply_uci_move(sim_board, mv)
                else:
                    # 使用 simulate 方法的逻辑手动展开，为了拿到 board 对象
                    sim_board, _ = ChessSimulation.fen_to_board(norm_base_fen)
                    move_list = history_moves.split() if history_moves else []
                    for mv in move_list:
                         ChessSimulation.apply_uci_move(sim_board, mv)
                
                #重建缓存
                cache['base_fen'] = norm_base_fen
                cache['moves_str'] = norm_history
                cache['board'] = [row[:] for row in sim_board]

            # 2. 在同步到当前 history_moves 的棋盘上，执行【当前这一步】
            # 注意：不能修改 sim_board，因为 sim_board 代表的是 confirmed history
            # 我们需要在一个临时副本上应用 pending move
            verify_board = [row[:] for row in sim_board]
            ChessSimulation.apply_uci_move(verify_board, move_str)
            
            # 3. 计算视觉FEN
            visual_fen, _ = utils.convert_array_to_fen(current_board, self.is_red)
            
            # 4. 计算推演FEN
            sim_fen = ChessSimulation.board_to_fen(verify_board)
            
            # 5. 比对
            if sim_fen and sim_fen != visual_fen:
                # 再次确认：如果是开局阶段，可能存在误判，放宽标准？
                # 暂时保持严格校验
                logger.warning(f"History Mismatch! Sim: {sim_fen} vs Visual: {visual_fen}")
                logger.warning(f"  Pending Move: {move_str}")
                logger.warning(f"  History Base: {base_fen}")
                logger.warning(f"  History Moves: {history_moves}")
                
                result.is_history_mismatch = True
                result.message += " (历史不一致)"
