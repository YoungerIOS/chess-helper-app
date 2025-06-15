class PositionChecker:
    def __init__(self):
        self.last_pieces_array = None  # 上一次的棋盘数组

    def check_position_changes(self, array1, array2):
        """
        检查两个棋盘数组之间的变化
        返回: (是否变化, 棋子总量变化, 红方变化位置列表, 黑方变化位置列表)
        """
        if not array2:
            return False, 0, [], []
        
        has_changes = False
        red_changes = []    # 红方变化位置 [(row, col, old_piece, new_piece), ...]
        black_changes = []  # 黑方变化位置 [(row, col, old_piece, new_piece), ...]
        
        # 统计棋子数量
        red_count1 = 0
        black_count1 = 0
        red_count2 = 0
        black_count2 = 0
        
        # 遍历两个数组的每个位置
        for i in range(len(array1)):
            for j in range(len(array1[i])):
                piece1 = array1[i][j]
                piece2 = array2[i][j]
                
                # 统计棋子数量
                if piece1.isupper() and piece1 != '-':  # 红方棋子
                    red_count1 += 1
                elif piece1.islower() and piece1 != '-':  # 黑方棋子
                    black_count1 += 1
                    
                if piece2.isupper() and piece2 != '-':  # 红方棋子
                    red_count2 += 1
                elif piece2.islower() and piece2 != '-':  # 黑方棋子
                    black_count2 += 1
                
                # 检查位置是否发生变化
                if piece1 != piece2:
                    has_changes = True
                    
                    # 判断变化的是红方还是黑方棋子
                    if piece1.isupper() and piece1 != '-':  # 原来是红方棋子
                        red_changes.append((i, j, piece1, piece2))
                    elif piece1.islower() and piece1 != '-':  # 原来是黑方棋子
                        black_changes.append((i, j, piece1, piece2))
                    elif piece2.isupper() and piece2 != '-':  # 新位置是红方棋子
                        red_changes.append((i, j, piece1, piece2))
                    elif piece2.islower() and piece2 != '-':  # 新位置是黑方棋子
                        black_changes.append((i, j, piece1, piece2))
        
        # 计算棋子总量变化 (红方 + 黑方)
        total_change = (red_count2 + black_count2) - (red_count1 + black_count1)
        
        # 验证变化是否合理
        # if len(red_changes) > 2 or len(black_changes) > 2:  # 每步棋最多只能移动一个棋子
        #     return False, total_change, red_changes, black_changes
            
        # if abs(total_change) > 1:  # 每步棋最多只能吃一个棋子
        #     return False, total_change, red_changes, black_changes
        
        return has_changes, total_change, red_changes, black_changes


    def get_available_changes(self, current_pieces_array):
        """
        检查当前局面是否有可用的改变
        返回: (是否变化, 红方变化位置列表, 黑方变化位置列表)
        """
        # 第一次调用
        if self.last_pieces_array is None:
            self.last_pieces_array = current_pieces_array
            return True, [], []
            
        # 检查具体的变化位置
        has_changes, _, red_changes, black_changes = self.check_position_changes(
            self.last_pieces_array, current_pieces_array)
        
        # 只有在检测到变化时才更新last_board_array
        if has_changes:
            self.last_pieces_array = current_pieces_array
            
        return has_changes, red_changes, black_changes 