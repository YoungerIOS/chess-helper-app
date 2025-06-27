import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
from app.chess.checker import PositionChecker

# 初始棋盘
BOARD1 = [
    ['r', 'n', 'b', 'a', 'k', 'a', 'b', 'n', 'r'],  # 黑方
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['-', 'c', '-', '-', '-', '-', '-', 'c', '-'],
    ['p', '-', 'p', '-', 'p', '-', 'p', '-', 'p'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['P', '-', 'P', '-', 'P', '-', 'P', '-', 'P'],
    ['-', 'C', '-', '-', '-', '-', '-', 'C', '-'],
    ['-', '-', '-', '-', '-', '-', '-', '-', '-'],
    ['R', 'N', 'B', 'A', 'K', 'A', 'B', 'N', 'R']   # 红方
]

def print_board(board):
    """打印棋盘"""
    for row in board:
        print(' '.join(row))
    print()

def print_result(result):
    """打印检查结果"""
    print("检查结果:")
    print(f"棋盘是否合法: {result.is_valid}")
    print(f"是否有变化: {result.has_changes}")
    print(f"是否单步: {result.is_single_step}")
    print(f"是否多步: {result.is_multi_step}")
    print(f"信息: {result.message}")
    
    if result.step_info:
        print("\n移动信息:")
        print(f"起始位置: {result.step_info.get('from_pos')}")
        print(f"目标位置: {result.step_info.get('to_pos')}")
        print(f"移动棋子: {result.step_info.get('piece')}")
        print(f"移动方: {result.step_info.get('side')}")
        if result.step_info.get('captured_piece'):
            print(f"被吃棋子: {result.step_info.get('captured_piece')}")

def run_tests():
    """运行所有测试"""
    print("开始测试...")
    checker = PositionChecker()
    
    # 测试1：初始化棋盘
    print("\n测试1：初始化棋盘")
    result = checker.check_board(BOARD1)
    print_board(BOARD1)
    print_result(result)
    assert result.is_valid
    
    # 测试2：正常移动
    print("\n测试2：正常移动")
    board = [row[:] for row in BOARD1]
    board[9][1] = '-'  # 移除红马
    board[7][2] = 'N'  # 放置红马在新位置
    result = checker.check_board(board)
    print_board(board)
    print_result(result)
    assert result.is_valid and result.is_single_step
    
    # 测试3：吃子移动
    print("\n测试3：吃子移动")
    board = [row[:] for row in board]  # 使用上一次的棋盘
    board[2][7] = '-'  # 移动黑炮
    board[9][7] = 'c'  # 吃掉红马
    result = checker.check_board(board)
    print_board(board)
    print_result(result)
    assert result.is_valid and result.is_single_step

    # 测试3b：蹩马腿（非法马步）
    print("\n测试3b：蹩马腿（非法马步）")
    board = [row[:] for row in board]
    # 假设红马在(7,2)，(8,2)有兵挡马腿，尝试让马走日字到(9,1)
    board[0][1] = '-'  # 红马离开原位
    board[2][2] = 'n'  # 红马尝试跳到(9,1)
    # (8,2)有兵，不应允许此步
    result = checker.check_board(board)
    print_board(board)
    print_result(result)
    assert not result.is_valid

    # 测试7：丢失两步移动的推断
    print("\n测试7：丢失两步移动的推断")
    board = [row[:] for row in board]
    board[6][2] = '-'
    board[5][2] = 'P'
    board[2][1] = '-'
    board[2][4] = 'c'
    result = checker.check_board(board)
    print_board(board)
    print_result(result)
    # 推断功能暂未集成到BoardStatus，略过断言

    # 测试4：非法移动
    print("\n测试4：非法移动")
    board = [row[:] for row in board]
    board[7][7] = '-'
    board[1][7] = 'C'
    result = checker.check_board(board)
    print_board(board)
    print_result(result)
    assert not result.is_valid
    
    # 测试5：多步移动
    print("\n测试5：多步移动")
    board = [row[:] for row in board]
    board[6][4] = '-'
    board[5][4] = 'P'
    board[9][8] = '-'
    board[8][7] = 'R'
    result = checker.check_board(board)
    print_board(board)
    print_result(result)
    assert result.is_valid and result.is_multi_step
    
    # 测试8：丢失三步移动的推断
    print("\n测试8：丢失三步移动的推断")
    board = [row[:] for row in BOARD1]
    board[9][1] = '-'
    board[7][2] = '-'
    board[5][3] = '-'
    board[3][4] = 'N'
    board[9][8] = '-'
    board[7][7] = '-'
    board[5][6] = 'R'
    result = checker.check_board(board)
    print_board(board)
    print_result(result)
    # 推断功能暂未集成到BoardStatus，略过断言
    
    print("\n所有测试完成!\n")

if __name__ == '__main__':
    run_tests() 