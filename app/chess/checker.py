from dataclasses import dataclass, field
from typing import Optional, Dict, Any

@dataclass
class BoardStatus:
    is_illegal: bool = False
    is_same_board: bool = False
    is_my_step: bool = False
    is_opponent_step: bool = False
    is_multi_step: bool  = False
    is_new_game: bool = False 
    is_red_start: bool = False
    is_black_start: bool = False
    step_info: Optional[Dict[str, Any]] = field(default_factory=dict)
    message: str = ""
    

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

    def __init__(self):
        self.is_red = True
        self.last_board = None  # 上一次的棋盘数组
        self.last_counts = None  # 上一次的棋子数量统计
        self.red_start_count = 0  # 红方开局局面连续出现次数 
        self.consecutive_drops = 0 # 连续丢帧计数(防卡死) 
        
    def reset(self):
        """重置检查器状态，用于手动刷新时清除历史状态"""
        self.last_board = None
        self.last_counts = None

    def force_sync_board(self, board_array):
        """强制同步棋盘状态（用于处理连续非法帧导致的卡死）"""
        self.last_board = [row[:] for row in board_array]
        # 获取当前棋子数量统计（忽略合法性检查结果，只取计数）
        _, _, self.last_counts = self.check_pieces_count(board_array)
        self.consecutive_drops = 0
        self.red_start_count = 0  # 重置红方开局触发计数
        print("Debug - 检查器状态已重置 (Force Sync)")

    def is_red_at_bottom(self, board_array):
        """通过黑王的位置判断红方是否在棋盘底部"""
        for r in range(3):  # 上方九宫格是前3行
            for c in range(3, 6):
                if board_array[r][c] == 'k':
                    return True
        return False

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
        counts = {}
        for row in array:
            for piece in row:
                if piece != '-':
                    counts[piece] = counts.get(piece, 0) + 1
        
        if self.last_counts is None:
            return True, "重置局面", counts
        
        if counts.get('k', 0) != 1 or counts.get('K', 0) != 1:
            return False, f"非法将帅数量: 检测到{counts.get('k', 0)}个将,{counts.get('K', 0)}个帅", counts
        
        for piece, count in counts.items():
            if piece.lower() == 'k':
                continue
            if count > self.last_counts.get(piece, 0):
                # 棋子数量变多是不可能的（除非是新对局/悔棋/上一帧识别错了）
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
            if is_red_piece:
                return r2 >= 5 if is_red_at_bottom else r2 <= 4
            else:
                return r2 <= 4 if is_red_at_bottom else r2 >= 5

        def is_legal_advisor(r1, c1, r2, c2, is_red_piece):
            if abs(r1 - r2) != 1 or abs(c1 - c2) != 1: return False
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
                if red_start and a2[i][j] != self.START_RED[i][j]:
                    red_start = False
                if black_start and a2[i][j] != self.START_BLACK[i][j]:
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
                return BoardStatus(is_illegal=True, message='非法变化：无法解析为单步移动')

            # 检查移动合法性
            step_info = {
                'from_pos': src, 
                'to_pos': dst, 
                'piece': moving_piece,
                'side': 'red' if moving_piece.isupper() else 'black',
                'captured_piece': captured_piece
            }
            is_legal = self.is_step_legal(a1, a2, is_red_at_bottom, step_info)
            
            if not is_legal:
                return BoardStatus(is_illegal=True, message='非法的移动')

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
            return BoardStatus(is_illegal=True, message='非法移动：只有一个格子变化')
        
        # 默认返回多步移动
        return BoardStatus(is_illegal=True, message='非法或未知局面')

    def check_board(self, current_board, marker_coords=None):
        """
        检查当前局面是否合法
        Args:
            current_board: 当前局面数组
            marker_coords: 标记坐标列表 (可选)
        Returns:
            BoardStatus: 检查结果
        """
        if current_board is None:
            return None
        
        self.is_red = self.is_red_at_bottom(current_board)

        # 首次初始化
        if self.last_board is None:
            self.last_board = [row[:] for row in (self.START_RED if self.is_red else self.START_BLACK)]
            self.last_counts = self.START_COUNTS.copy()
        
        # 全面分析局面变化
        result = self.check_position_changes(self.last_board, current_board, self.is_red)
        
        # 0. 强制检查标记 (如果对局已开始)
        # 如果有上一次的局面记录，说明对局正在进行中。
        # 此时如果画面发生了变化（不是SameBoard），却没检测到标记，说明截图可能截到了中间态（比如棋子飞在半空，或者动画遮挡）
        # 此时应直接视为非法（丢弃并重试），而不是尝试瞎猜。
        if self.last_board is not None and not result.is_same_board and not marker_coords:
            # 特殊情况：如果是开局重置（Red/Black Start），可能没有标记
            # 同样，如果是明确的单步移动（is_my_step 或 is_opponent_step），也允许通过（视为标记检测漏检，但移动本身合法）
            if not (result.is_red_start or result.is_black_start or result.is_my_step or result.is_opponent_step):
                return BoardStatus(is_illegal=True, message="检测到局面变化但未检测到标记，丢弃帧")

        # 1. 检测初始局面
        if result.is_red_start:
            if self.red_start_count < 1: # 开局帧最大允许连续出现次数(决定开局时会显示几次开局走法)
                # 允许前两次返回红方开局
                self.red_start_count += 1
                self.last_board = [row[:] for row in self.START_RED]
                self.last_counts = self.START_COUNTS.copy()
                return result
            else:
                # 超过1次则视为相同画面
                return BoardStatus(is_same_board=True, message="红方开局（>1次）相同画面")
        if result.is_black_start:
            self.last_board = [row[:] for row in self.START_BLACK]
            self.last_counts = self.START_COUNTS.copy()
            return result
        
        # 2. 检测相同局面 (最高频情形)
        if result.is_same_board:
            return result
        
        # 3. 核心逻辑：利用标记判定归属 (优先级最高)
        # 如果检测到了标记，直接根据标记位置判定是谁走了棋
        if self.last_board and marker_coords:
            is_my_step = None
            
            for r, c in marker_coords:
                # 坐标越界检查
                if not (0 <= r < len(self.last_board) and 0 <= c < len(self.last_board[0])):
                    continue
                
                piece_last = self.last_board[r][c]
                piece_curr = current_board[r][c]
                
                # 寻找"移动源头"：上一帧有棋子，且当前帧该棋子已离开（变为空）
                # 注意：如果是吃子，目标位置在 last_board 也有子，但 curr_board 也有子（攻击者），所以不会误判
                # 只有 "上一帧有子 -> 当前帧无子" 才能唯一确定这是 From_Pos
                if piece_last != '-' and piece_curr == '-':
                    is_red_piece = piece_last.isupper()
                    # 判断该棋子是否归属我方
                    is_your_piece = (self.is_red and is_red_piece) or (not self.is_red and not is_red_piece)
                    
                    if is_your_piece:
                        # 我方棋子离开了 -> 我走了这步棋
                        is_my_step = True
                    else:
                        # 对方棋子离开了 -> 对方走了这步棋
                        is_my_step = False
                    
                    break 
            
            # 只有当确实找到了符合条件的标记时才覆盖结果
            if is_my_step is not None:
                result.is_my_step = is_my_step
                result.is_opponent_step = not is_my_step
                result.is_multi_step = False
                result.is_new_game = False
                result.is_illegal = False 
                result.message = f"标记判定: {'我方' if is_my_step else '对方'}走棋"
                
                # 更新状态
                self.last_board = [row[:] for row in current_board]
                
                # 尝试简单维护棋子数量，避免后续校验报错
                # (稍微粗糙点，直接统计当前数量即可，因为已经通过标记确认了合法性，数量校验只是辅助)
                _, _, current_counts_check = self.check_pieces_count(current_board)
                self.last_counts = current_counts_check

                self.red_start_count = 0
                return result

        # 4. 如果没有标记（通常被上面的 check 0 拦截，但为了代码健壮性保留旧逻辑作为 Fallback，或处理特殊情况）
        # 判断合法单步移动
        if result.is_my_step or result.is_opponent_step:
            self.last_board = [row[:] for row in current_board]
            p = result.step_info['captured_piece']
            if result.step_info and p:
                self.last_counts[p] = max(0, self.last_counts.get(p, 1) - 1)
            self.red_start_count = 0
            return result
        
        # 5. 过滤其他非法局面
        count_valid, count_msg, current_counts = self.check_pieces_count(current_board)
        if not count_valid:
            return BoardStatus(is_illegal=True, message=count_msg)
        
        if "重置" in count_msg:
             return BoardStatus(is_multi_step=True, step_info={}, message=count_msg)
        
        position_valid, position_msg = self.check_pieces_position(current_board, self.is_red)
        if not position_valid:
            return BoardStatus(is_illegal=True, message=position_msg)
        
        # 6. 多步移动或残局
        if result.is_multi_step:
            self.last_board = [row[:] for row in current_board]
            self.last_counts = current_counts.copy()
            result.is_new_game = True
            self.red_start_count = 0
            return result
        
        return result
