import time
import os
import sys
import subprocess
import threading
from typing import Optional, Tuple, List, Callable
from chess.message import Message, MessageType, MessageContent
from chess.context import context

class ChessEngine:
    """中国象棋引擎类，封装了与Pikafish引擎的交互"""
    
    def __init__(self, engine_path: str = None, threads: int = 4, hash_size: int = 256):
        """
        初始化象棋引擎
        
        Args:
            engine_path: 引擎可执行文件路径，如果为None则使用默认路径
            threads: 引擎使用的线程数
            hash_size: 引擎哈希表大小(MB)
        """
        self.engine_path = engine_path or self._get_default_engine_path()
        self.threads = threads
        self.hash_size = hash_size
        self.process: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        self.is_initialized = False
        
    def _get_default_engine_path(self) -> str:
        """获取默认引擎路径"""
        return self._resource_path("Pikafish/src/pikafish")
    
    def _resource_path(self, relative_path: str) -> str:
        """获取资源文件的绝对路径"""
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(os.path.abspath("./app/"), relative_path)
    
    def start(self) -> bool:
        """启动引擎"""
        with self.lock:
            try:
                if self.process is not None and self.process.poll() is None:
                    print("引擎已经在运行")
                    return True
                
                self.process = subprocess.Popen(
                    self.engine_path,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                self._initialize_engine()
                self.is_initialized = True
                print("引擎启动成功")
                return True
                
            except Exception as e:
                print(f"启动引擎时出错：{e}")
                self.process = None
                self.is_initialized = False
                return False
    
    def _initialize_engine(self):
        """初始化引擎设置"""
        self._send_command('uci')
        self._wait_for_response('uciok', timeout=1)
        
        self._send_command(f'setoption name Threads value {self.threads}')
        self._send_command(f'setoption name Hash value {self.hash_size}')
        time.sleep(0.2)
        
        self._send_command('isready')
        self._wait_for_response('readyok', timeout=1)
    
    def stop(self):
        """停止引擎"""
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                finally:
                    self.process = None
                    self.is_initialized = False
                    print("引擎已停止")
    
    def _send_command(self, command: str):
        """发送命令到引擎"""
        if not self.process:
            raise RuntimeError("引擎未启动")
        print(f"[ENGINE CMD] {command}")  # 调试用，打印实际发给引擎的命令
        self.process.stdin.write(f'{command}\n')
        self.process.stdin.flush()
    
    def _wait_for_response(self, keyword: str, timeout: float = 1.0) -> List[str]:
        """等待引擎响应，直到包含指定关键字"""
        if not self.process:
            return []
        
        lines = []
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            output = self.process.stdout.readline().strip()
            if output:
                lines.append(output)
                if keyword in output:
                    break
        
        return lines
    
    def new_game(self):
        """开始新游戏"""
        if not self.is_initialized:
            raise RuntimeError("引擎未初始化")
        
        self._send_command('ucinewgame')
        self._send_command('isready')
        self._wait_for_response('readyok', timeout=3)
    
    def _position(self, fen_string: str, use_startpos: bool = True, moves: Optional[str] = None):
        """
        发送position命令
        """
        if use_startpos:
            cmd = "position startpos"
            if moves:
                cmd += f" moves {moves}"
        else:
            cmd = f"position fen {fen_string}"
        self._send_command(cmd)

    def _go(self, param: str, value: str) -> Tuple[List[str], str]:
        """
        发送go命令和读取结果
        """
        self._send_command(f"go {param} {value}")
        return self._read_output_with_timeout(60)

    def get_bestmove(self, fen: str, side: bool, display_callback: Optional[Callable] = None, *, use_startpos: bool = True, is_newgame: bool = False, moves: Optional[str] = None) -> Tuple[str, str]:
        """获取最佳走法
        参数:
        - fen: FEN字符串
        - side: 当前轮到哪一方（True为红方，False为黑方）
        - display_callback: 显示回调函数
        - is_startpos: 是否用startpos（否则用fen）
        - is_newgame: 是否新局
        - moves: 历史走法字符串
        """
        if not self.is_initialized:
            raise RuntimeError("引擎未初始化")
        fen_string = ''
        if fen:
            fen_string = fen + ' ' + ('w' if side else 'b')
        engine_params = context.get_engine_params()
        param = engine_params.get('goParam', 'depth')
        value = engine_params.get(param, '20')
        if not param or not value:
            param = 'depth'
            value = '20'

        if display_callback:
            display_callback(Message(MessageType.STATUS, MessageContent.ENGINE_THINKING))

        if is_newgame:
            self.new_game()

        self._position(fen_string, use_startpos=use_startpos, moves=moves)
        lines, best_move = self._go(param, value)

        if not lines:
            best_move = "No output received within 40 seconds"
        else:
            if not best_move:
                best_move = ' '.join(lines)
            else:
                start_index = best_move.find('bestmove') + len('bestmove') + 1
                best_move = best_move[start_index:start_index + 4]
        return best_move, fen_string
    
    def verify_history(self, moves: str) -> str:
        """
        用历史moves复盘并用d命令获取FEN, 校验历史记录是否有误.
        """
        if not self.is_initialized:
            raise RuntimeError("引擎未初始化")
        self._send_command('position startpos moves ' + moves)
        self._send_command('d')
        # 读取输出直到出现Fen: ...
        fen = None
        start_time = time.time()
        while time.time() - start_time < 2.0:  # 最多等2秒
            output = self.process.stdout.readline()
            if not output:
                continue
            output = output.strip()
            if output.startswith('Fen:'):
                fen = output.split('Fen:')[1].strip()
                if fen:
                    fen = fen.split(' ')[0]
                break
        return fen or ""

    def _read_output_with_timeout(self, timeout: float = 1.0) -> Tuple[List[str], str]:
        """读取引擎输出，带超时控制"""
        lines = []
        best_move = ''
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            output = self.process.stdout.readline().strip()
            if output:
                lines.append(output)
                if "bestmove" in output:
                    best_move = output
                    break
        
        return lines, best_move
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.stop()
    
    def __del__(self):
        """析构函数，确保资源被正确释放"""
        self.stop()



