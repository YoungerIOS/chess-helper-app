from typing import ClassVar


class ChessSimulation:
    """
    轻量级中国象棋模拟器 (纯Python实现)
    用于在不依赖引擎的情况下，根据 Startpos/FEN 和 moves 推演最终局面。
    """

    # 红方在下面的标准初始局面
    START_RED_BOTTOM: ClassVar[list[list[str]]] = [
        ["r", "n", "b", "a", "k", "a", "b", "n", "r"],
        ["-", "-", "-", "-", "-", "-", "-", "-", "-"],
        ["-", "c", "-", "-", "-", "-", "-", "c", "-"],
        ["p", "-", "p", "-", "p", "-", "p", "-", "p"],
        ["-", "-", "-", "-", "-", "-", "-", "-", "-"],
        ["-", "-", "-", "-", "-", "-", "-", "-", "-"],
        ["P", "-", "P", "-", "P", "-", "P", "-", "P"],
        ["-", "C", "-", "-", "-", "-", "-", "C", "-"],
        ["-", "-", "-", "-", "-", "-", "-", "-", "-"],
        ["R", "N", "B", "A", "K", "A", "B", "N", "R"],
    ]

    @staticmethod
    def simulate(base_fen: str, moves_str: str) -> str:
        """
        核心方法：给定起始FEN（None表示startpos）和着法串，推演最终FEN
        Returns:
            final_fen_str (不包含 turn/castling/clock 等后缀，只返回棋盘部分的FEN)
        """
        # 1. 初始化棋盘
        if not base_fen or base_fen == "startpos":
            # 默认使用红方在下的标准开局
            board = [row[:] for row in ChessSimulation.START_RED_BOTTOM]
            # UCI着法通常假设红方控制权，或者说它是基于坐标的操作
            # 我们统一视为红方在下进行模拟
            is_red_turn = True
        else:
            board, turn_char = ChessSimulation.fen_to_board(base_fen)
            is_red_turn = turn_char == "w"

        # 2. 解析着法列表
        if not moves_str:
            return ChessSimulation.board_to_fen(board)

        move_list = moves_str.split()

        # 3. 逐步演练
        for move in move_list:
            ChessSimulation.apply_uci_move(board, move)
            is_red_turn = (
                not is_red_turn
            )  # 切换行动方（虽然对于FEN生成只看棋盘分布，不看轮次）

        # 4. 转回 FEN
        return ChessSimulation.board_to_fen(board)

    @staticmethod
    def fen_to_board(fen):
        """解析FEN到 9x10 数组"""
        parts = fen.split()
        board_part = parts[0]
        turn = parts[1] if len(parts) > 1 else "w"

        rows = board_part.split("/")
        board = []
        for r_str in rows:
            row = []
            for char in r_str:
                if char.isdigit():
                    row.extend(["-"] * int(char))
                else:
                    row.append(char)
            board.append(row)
        return board, turn

    @staticmethod
    def board_to_fen(board):
        """将数组转回 FEN (仅棋盘部分)"""
        fen_rows = []
        for row in board:
            empty = 0
            row_str = ""
            for cell in row:
                if cell == "-":
                    empty += 1
                else:
                    if empty > 0:
                        row_str += str(empty)
                        empty = 0
                    row_str += cell
            if empty > 0:
                row_str += str(empty)
            fen_rows.append(row_str)
        return "/".join(fen_rows)

    @staticmethod
    def apply_uci_move(board, uci_move):
        """
        在 board 上执行 UCI 着法 (例如 h2e2)
        注意：UCI 坐标系是类似于标准的象棋坐标系，但也可能是基于 ICCS 的。
        Pikafish/UCI 协议的坐标定义：
        - 列: a-i (从左到右, 0-8)
        - 行: 0-9 (从下到上! 0是底部, 9是顶部)

        所以 board[row][col] mapping:
        - UCI col 'a' -> board col 0
        - UCI row '0' -> board row 9 (数组最下面一行)
        - UCI row '9' -> board row 0 (数组最上面一行)
        """
        if len(uci_move) < 4:
            return

        cols = "abcdefghi"

        c1 = cols.find(uci_move[0])
        r1 = int(uci_move[1])
        c2 = cols.find(uci_move[2])
        r2 = int(uci_move[3])

        # 转换到数组坐标 (Array Row = 9 - UCI Row)
        # 数组: row 0 is top, row 9 is bottom
        # UCI: row 9 is top, row 0 is bottom
        from_r, from_c = 9 - r1, c1
        to_r, to_c = 9 - r2, c2

        # 执行移动 (覆盖)
        piece = board[from_r][from_c]
        board[to_r][to_c] = piece
        board[from_r][from_c] = "-"
