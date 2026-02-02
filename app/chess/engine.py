import time
import os
import sys
import subprocess
import threading
from typing import Optional, Tuple, List, Callable
from app.chess.message import Message, MessageType, MessageContent
from app.chess.context import context
from app.tools.utils import resource_path
from app.tools.log_config import get_logger

logger = get_logger(__name__)

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
        self.analysis_lock = threading.Lock()
        self.is_initialized = False
        
    def _get_default_engine_path(self) -> str:
        """获取默认引擎路径"""
        from app.tools.utils import app_data_path
        
        # 优先使用用户数据目录中的引擎文件
        user_engine_path = app_data_path("Pikafish/pikafish")
        if os.path.exists(user_engine_path) and os.access(user_engine_path, os.X_OK):
            return user_engine_path
        
        # 备用：使用打包后的资源
        fallback_path = resource_path("Pikafish", "src", "pikafish")
        if os.path.exists(fallback_path):
            return fallback_path
        
        # 如果都不存在，返回用户数据目录路径（用于首次复制）
        return user_engine_path
    
    def start(self) -> bool:
        """启动引擎"""
        with self.lock:
            try:
                if self.process is not None and self.process.poll() is None:
                    print("引擎已经在运行")
                    return True
                
                # 检查引擎文件是否存在
                if not os.path.exists(self.engine_path):
                    logger.error(f"引擎文件不存在: {self.engine_path}")
                    return False
                
                # 确保可执行权限
                try:
                    if os.path.exists(self.engine_path) and not os.access(self.engine_path, os.X_OK):
                        os.chmod(self.engine_path, 0o755)
                except Exception:
                    pass

                self.process = subprocess.Popen(
                    self.engine_path,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                self._initialize_engine()
                self.is_initialized = True
                logger.info("引擎启动成功")
                return True
                
            except Exception as e:
                logger.error(f"启动引擎时出错：{e}")
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
    
    def quit(self):
        """停止引擎"""
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    # 先尝试发送quit命令让引擎优雅退出
                    self._send_command('quit')
                    # 等待引擎进程自然结束
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    # 如果1秒内没结束，强制终止
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except Exception:
                    # 如果发送命令失败，直接终止进程
                    self.process.terminate()
                    self.process.wait(timeout=2)
                finally:
                    # 如果进程仍然存在，强制杀死
                    if self.process and self.process.poll() is None:
                        self.process.kill()
                        self.process.wait(timeout=1)
                    self.process = None
                    self.is_initialized = False
                    logger.info("引擎已停止")
    
    def _send_command(self, command: str):
        """发送命令到引擎"""
        if not self.process:
            raise RuntimeError("引擎未启动")
        # print(f"[ENGINE CMD] {command}")  # 调试用，打印实际发给引擎的命令
        try:
            self.process.stdin.write(f'{command}\n')
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            # 如果进程已经退出，忽略错误
            pass

    def stop_analysis(self):
        """发送停止分析命令(用于超时强制停止)"""
        try:
            self._send_command('stop')
            logger.info("Sent 'stop' command to engine")
        except Exception as e:
            logger.error(f"Failed to send stop command: {e}")
    
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
            if moves:
                cmd += f" moves {moves}"
        self._send_command(cmd)

    def _go(self, param: str, value: str) -> Tuple[List[str], str, List[dict]]:
        """
        发送go命令和读取结果
        """
        self._send_command(f"go {param} {value}")
        return self._read_output_with_timeout(35)

    def get_bestmove(self, fen: str, side: bool, display_callback: Optional[Callable] = None, *, use_startpos: bool = True, is_newgame: bool = False, moves: Optional[str] = None, multipv: int = 1) -> Tuple[str, str, List[str]]:
        """获取最佳走法
        Returns:
            (best_move, fen_string, pvs_list)
        """
        if not self.is_initialized:
            raise RuntimeError("引擎未初始化")
        
        # 尝试获取分析锁
        # 如果获取失败，说明有其他线程正在分析，发送stop尝试中断它
        if not self.analysis_lock.acquire(blocking=False):
            # print("Debug - 引擎正忙，尝试通过发送 stop 中断...")
            self._send_command('stop')
            # 阻塞等待，直到上一个任务释放锁
            self.analysis_lock.acquire()
            
        try:
            # 此时我们拥有独占锁 且 （如果有前任务）前任务已结束
            # 再次发送 stop 确保引擎状态 (对于某些情况可能多余，但比较稳妥)
            self._send_command('stop')
            
            # 设置 MultiPV
            if multipv > 1:
                self._send_command(f'setoption name MultiPV value {multipv}')
            
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
            lines, best_move, pvs = self._go(param, value)

            # 恢复 MultiPV 为 1 (以免影响后续正常思考)
            if multipv > 1:
                self._send_command('setoption name MultiPV value 1')

            if not lines:
                best_move = None
                # logger.warning("No output received from engine (timeout)")
            else:
                if not best_move:
                     # [FIX] Fallback removal
                     logger.error(f"Engine timeout without bestmove! Raw output len: {len(lines)}")
                     best_move = None
                else:
                    # 调试：打印原始 bestmove 响应
                    print(f"Debug - Engine raw response: {best_move}")
                    start_index = best_move.find('bestmove') + len('bestmove') + 1
                    best_move = best_move[start_index:start_index + 4]
                    
                    # 检查是否为无效着法（如 "(none)" 或 "0000"）
                    if best_move.startswith('(') or best_move == '0000' or not best_move[0].isalpha():
                        print(f"Debug - Engine returned invalid move: {best_move}")
                        best_move = ""  # 返回空，让调用者处理
            
            # 提取 PV 中的第一个着法
            pv_moves = []
            for pv_info in pvs:
                # pv_info is a dict like {'multipv': 1, 'pv_str': 'h2e2 ...', 'score': ...}
                if 'pv_str' in pv_info:
                    moves_list = pv_info['pv_str'].split()
                    if moves_list:
                        pv_moves.append(moves_list[0])

            return best_move, fen_string, pv_moves
            
        finally:
            # 确保释放锁
            self.analysis_lock.release()
    


    def _read_output_with_timeout(self, timeout: float = 1.0) -> Tuple[List[str], str, List[dict]]:
        """读取引擎输出，带超时控制
        Returns:
            lines: 所有输出行
            best_move: bestmove 行
            pvs: 解析出的 pv 信息列表 [{'multipv': 1, 'score': ..., 'pv_str': ...}, ...]
        """
        lines = []
        best_move = ''
        pvs = {} # Key: multipv_id, Value: info_dict
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            output = self.process.stdout.readline().strip()
            if output:
                lines.append(output)
                if output.startswith('info') and ' multipv ' in output and ' pv ' in output:
                    # 解析 info 行
                    try:
                        parts = output.split()
                        
                        # 提取 multipv ID
                        multipv_idx = -1
                        if 'multipv' in parts:
                            multipv_idx = int(parts[parts.index('multipv') + 1])
                        
                        # 提取 pv 字符串 (从 pv 之后所有内容)
                        pv_str = ""
                        if 'pv' in parts:
                            pv_start = parts.index('pv') + 1
                            pv_str = " ".join(parts[pv_start:])
                        
                        # 存入字典 (后续的更新会覆盖前面的，保证保留同一 depth 最新的)
                        # 注意：info 行可能很多，我们只关心最后出现的
                        if multipv_idx != -1:
                            pvs[multipv_idx] = {'multipv': multipv_idx, 'pv_str': pv_str}
                            
                    except Exception:
                        pass
                        
                if "bestmove" in output:
                    best_move = output
                    break
        
        # 将 pvs 字典转为按 multipv 排序的列表
        sorted_pvs = [pvs[k] for k in sorted(pvs.keys())]
        
        return lines, best_move, sorted_pvs
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.quit()
    
    def __del__(self):
        """析构函数，确保资源被正确释放"""
        self.quit()



