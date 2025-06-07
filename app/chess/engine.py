import time
import os
import sys
import subprocess
import threading
from chess.message import Message, MessageType
from chess.context import context

#使用线程锁,可以确保任何时刻只有一个线程可以访问pikafish变量
#在这里用处可能不大,但感觉日后如果要面对大量用户同时使用,可能用得上
pikafish_lock = threading.Lock()
pikafish = None

def init_engine():
    global pikafish # 全局变量

    with pikafish_lock:
        # 检查 pikafish 是否已经存在且正在运行  
        if pikafish is not None and pikafish.poll() is None:  
            print("Pikafish 引擎已经在运行")  
            return 
        # 如果 pikafish 不存在或者已经停止，则重新启动
        elif pikafish is None or pikafish.poll() is not None:
            # 开辟一个子进程, 运行引擎
            # 读取存在本地的坐标 
            pikafish_command = resource_path("Pikafish/src/pikafish")
            try:  
                pikafish = subprocess.Popen(pikafish_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) 
                print("Pikafish 引擎已启动。")  
            except Exception as e:  
                print(f"启动 Pikafish 引擎时出错：{e}")  
                pikafish = None  # 如果启动失败，将 pikafish 设置为 None

    # 准备
    uci(pikafish) # 可以用全局变量,也可以用传参
    send_command('setoption name Threads value 2', 1, 'threads')
    set_option('setoption name Hash value 256')
    isready()

def terminate_engine():
    # 安全地关闭引擎进程
    global pikafish
    with pikafish_lock:
        if pikafish and pikafish.poll() is None:  # 检查进程是否还在运行  
            pikafish.terminate()  # 发送 SIGTERM 信号  
            try:  
                # 可选：等待进程结束
                pikafish.wait(timeout=3)  # 等待最多3秒  
            except subprocess.TimeoutExpired:  
                pikafish.kill()  # 如果超时，则强制杀死进程  
            finally:  
                pikafish = None
                print("Pikafish 引擎已关闭。")

def resource_path(relative_path):  
    """ 获取资源文件的绝对路径 """  
    if hasattr(sys, '_MEIPASS'):  
        # 如果是打包后的应用，则使用 sys._MEIPASS  
        return os.path.join(sys._MEIPASS, relative_path)  
    return os.path.join(os.path.abspath("./app/"), relative_path)
    
def get_best_move(fen, side, display_callback=None):
    fen_string = fen + ' ' + ('w' if side else 'b')

    # 从上下文获取引擎参数
    engine_params = context.get_engine_params()
    param = engine_params['goParam']
    value = engine_params[param]
    if param is None or param == '' or value is None or value == '':
        param = 'depth'
        value = '20'

    # 显示计算状态
    if display_callback:
        display_callback(Message(MessageType.STATUS, "引擎正在计算..."))

    lines, best_move = go(fen_string, param, value)

    if not lines:  
        best_move = "No output received within 40 seconds. code:408"  # 使用408 Request Timeout作为HTTP状态码  
    else:
        if not best_move:
            best_move = ' '.join(lines)
        else:
            # 截取4个字符
            start_index = best_move.find('bestmove') + len('bestmove') + 1
            best_move = best_move[start_index:start_index + 4]

    return best_move, fen_string

def send_command(cmd, interval, keyword):
    command = cmd
    pikafish.stdin.write(f'{command}\n')    
    pikafish.stdin.flush() 
    lines = []
    start_time = time.time()
    while True:  
        # 读取一行输出（包括换行符），然后去除换行符  
        output = pikafish.stdout.readline().strip()  
        if (time.time() - start_time > interval):  # 如果超过指定时间，则退出循环  
            break  
        if output:  
            lines.append(output)  # 将非空输出添加到列表中  
            if keyword in output:  # 如果找到 输出关键字，则立即退出循环  
                break  
    return lines

def uci(engine):
    command = 'uci'
    engine.stdin.write(f'{command}\n')    
    engine.stdin.flush() 
    lines = []
    start_time = time.time()
    while True:  
        # 读取一行输出（包括换行符），然后去除换行符  
        output = engine.stdout.readline().strip()  
        if (time.time() - start_time > 1):  # 如果超过1秒，则退出循环  
            break  
        if output:  
            lines.append(output)  # 将非空输出添加到列表中  
            if 'uciok' in output:  # 如果找到 'uciok'，则立即退出循环  
                break  
    return lines

def isready():
    command = 'isready'
    pikafish.stdin.write(f'{command}\n')    
    pikafish.stdin.flush() 
    time.sleep(0.5)
    output = pikafish.stdout.readline().strip()
    return output

def set_option(cmd):
    command = cmd
    pikafish.stdin.write(f'{command}\n')    
    pikafish.stdin.flush() 
    time.sleep(0.2)
    return

def ucinewgame():
    """
    发送ucinewgame之后应该总是发送isready命令,然后等待readyok
    """
    newgame_command = 'ucinewgame\n'
    isready_command = 'isready\n'
    pikafish.stdin.write(newgame_command)
    pikafish.stdin.write(isready_command)
    pikafish.stdin.flush() 
    start_time = time.time()
    while True:  
        output = pikafish.stdout.readline().strip()  
        if (time.time() - start_time > 3):  # 如果超过3秒，则退出循环 
            break  
        if output:  
            if 'readyok' in output:  
                break  
    return output

def go(fen_string, param, value):
    start_position1 = 'rnbakabnr/9/1c5c1/p1p1p1p1p'
    start_position2 = 'P1P1P1P1P/1C5C1/9/RNBAKABNR'
    if start_position1 in fen_string or start_position2 in fen_string:
        ucinewgame()
        pos_command1 = "position startpos\n"
        pikafish.stdin.write(pos_command1)

    pos_command2 = "position fen " + fen_string + "\n"  
    go_command = "go " + param + " " + value + "\n" 
    # 发送命令  
    pikafish.stdin.write(pos_command2)  
    pikafish.stdin.write(go_command)  
    pikafish.stdin.flush() 
    # 读取数据
    lines, best_move = read_output_with_timeout(pikafish, 50)

    return lines, best_move

def read_output_with_timeout(process, timeout=1):  
    lines = []
    best_move = ''
    start_time = time.time()  
    
    while True:  
        # 读取一行输出（包括换行符），然后去除换行符  
        output = process.stdout.readline().strip()  
        # 控制读取时间,超时不再读取 
        if time.time() - start_time > timeout:  
            break
        if output: 
            lines.append(output)
            if "bestmove" in output:
                best_move = output  # 获取包含"bestmove"的输出行
                break
    
    # 返回: 所有输出以及包含bestmove的行            
    return lines, best_move 
