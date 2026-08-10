import time
import os
import sys
import subprocess
import threading
import glob
from typing import Optional, Tuple, List, Callable
from app.chess.message import Message, MessageType
from app.chess.context import context
from app.tools.utils import resource_path
from app.tools.log_config import get_logger

logger = get_logger(__name__)

class ChessEngine:
    """中国象棋引擎类，封装了与Pikafish引擎的交互"""
    
    def __init__(
        self,
        engine_path: Optional[str] = None,
        threads: Optional[int] = None,
        hash_size: Optional[int] = None,
    ):
        """
        初始化象棋引擎
        
        Args:
            engine_path: 引擎可执行文件路径，如果为None则使用默认路径
            threads: 引擎使用的线程数；为None时从配置读取
            hash_size: 引擎哈希表大小(MB)；为None时从配置读取
        """
        engine_params = context.get_engine_params()
        self.engine_path = engine_path or self._get_default_engine_path()
        self.threads = self._parse_option(
            threads if threads is not None else engine_params.get('threads'),
            default=8,
            minimum=1,
            maximum=128,
        )
        self.hash_size = self._parse_option(
            hash_size if hash_size is not None else engine_params.get('hash'),
            default=256,
            minimum=16,
            maximum=32768,
        )
        self.process: Optional[subprocess.Popen] = None
        self.last_error = ""
        self.lock = threading.Lock()
        self.analysis_lock = threading.Lock()
        self.is_initialized = False

    @staticmethod
    def _parse_option(value, default: int, minimum: int, maximum: int) -> int:
        """解析并限制引擎整数参数，避免损坏的配置导致引擎启动失败。"""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))
        
    def _get_default_engine_path(self) -> str:
        """获取默认引擎路径"""
        from app.tools.utils import app_data_path

        # Windows release archives contain several CPU-specific executables.
        # Prefer the fastest broadly compatible builds and never auto-select
        # AVX-512/VNNI builds, which crash with 0xC000001D on older CPUs.
        if sys.platform == "win32":
            names = (
                "pikafish.exe",
                "pikafish-bmi2.exe",
                "pikafish-avx2.exe",
                "pikafish-sse41-popcnt.exe",
            )
            candidates = [app_data_path(f"Pikafish/{name}") for name in names]
            candidates.extend(resource_path("Pikafish", "src", name) for name in names)
            for candidate in candidates:
                if os.path.isfile(candidate):
                    return candidate
            return candidates[0]

        # macOS/Linux legacy layout.
        user_engine_path = app_data_path("Pikafish/pikafish")
        if os.path.isfile(user_engine_path) and os.access(user_engine_path, os.X_OK):
            return user_engine_path
        fallback_path = resource_path("Pikafish", "src", "pikafish")
        return fallback_path if os.path.isfile(fallback_path) else user_engine_path

    def _describe_process_failure(self) -> str:
        if self.process is None:
            return "引擎进程未创建"
        return_code = self.process.poll()
        if return_code is None:
            return "引擎未返回 UCI 就绪响应"
        if sys.platform == "win32":
            unsigned_code = return_code & 0xFFFFFFFF
            if unsigned_code == 0xC000001D:
                return "引擎包含当前 CPU 不支持的指令（0xC000001D），请改用 BMI2、AVX2 或 SSE4.1 版本"
            return f"引擎进程已退出（0x{unsigned_code:08X}）"
        return f"引擎进程已退出（code={return_code}）"
    
    def start(self) -> bool:
        """启动引擎"""
        with self.lock:
            try:
                self.last_error = ""
                if self.process is not None and self.process.poll() is None:
                    print("引擎已经在运行")
                    return True
                
                # 检查引擎文件是否存在
                if not os.path.exists(self.engine_path):
                    engine_dir = os.path.dirname(self.engine_path)
                    found = ", ".join(os.path.basename(path) for path in glob.glob(os.path.join(engine_dir, "pikafish*.exe")))
                    self.last_error = f"未找到兼容的引擎: {self.engine_path}"
                    if found:
                        self.last_error += f"；目录中现有: {found}"
                    logger.error(self.last_error)
                    return False
                
                # 确保可执行权限
                try:
                    if os.path.exists(self.engine_path) and not os.access(self.engine_path, os.X_OK):
                        os.chmod(self.engine_path, 0o755)
                except Exception:
                    pass

                popen_kwargs = {}
                if sys.platform == "win32":
                    popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                self.process = subprocess.Popen(
                    self.engine_path,
                    cwd=os.path.dirname(os.path.abspath(self.engine_path)),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **popen_kwargs,
                )
                
                self._initialize_engine()
                self.is_initialized = True
                logger.info("引擎启动成功")
                return True
                
            except Exception as e:
                detail = self._describe_process_failure()
                self.last_error = f"{e}；{detail}" if str(e) else detail
                logger.error(f"启动引擎时出错：{self.last_error}")
                if self.process is not None and self.process.poll() is None:
                    self.process.kill()
                    self.process.wait(timeout=1)
                self.is_initialized = False
                return False
    
    def _initialize_engine(self):
        """初始化引擎设置"""
        self._send_command('uci')
        uci_lines = self._wait_for_response('uciok', timeout=3)
        if not any('uciok' in line for line in uci_lines):
            raise RuntimeError("引擎没有完成 UCI 握手")

        nnue_path = os.path.join(os.path.dirname(os.path.abspath(self.engine_path)), "pikafish.nnue")
        if not os.path.isfile(nnue_path):
            raise FileNotFoundError(f"NNUE 文件不存在: {nnue_path}")
        # The engine process also runs in this directory; using the short name
        # avoids UCI parsing issues with spaces/non-ASCII path components.
        self._send_command('setoption name EvalFile value pikafish.nnue')
        
        self._send_command(f'setoption name Threads value {self.threads}')
        self._send_command(f'setoption name Hash value {self.hash_size}')
        logger.info(
            f"Pikafish配置: Threads={self.threads}, Hash={self.hash_size}MB"
        )
        time.sleep(0.2)
        
        self._send_command('isready')
        ready_lines = self._wait_for_response('readyok', timeout=10)
        if not any('readyok' in line for line in ready_lines):
            raise RuntimeError("引擎未能加载 NNUE 或未返回 readyok")

    def set_threads(self, threads: int) -> bool:
        """安全地更新线程数；引擎未运行时只更新实例配置。"""
        new_threads = self._parse_option(
            threads,
            default=self.threads,
            minimum=1,
            maximum=128,
        )

        # Pikafish不应在搜索过程中修改Threads。等待当前分析结束，同时
        # 使用生命周期锁避免与start/quit并发操作进程。
        with self.analysis_lock:
            with self.lock:
                self.threads = new_threads
                if (
                    not self.is_initialized
                    or self.process is None
                    or self.process.poll() is not None
                ):
                    return False

                self._send_command(f'setoption name Threads value {self.threads}')
                self._send_command('isready')
                responses = self._wait_for_response('readyok', timeout=3)
                applied = any('readyok' in line for line in responses)
                if applied:
                    logger.info(f"Pikafish线程数已更新: Threads={self.threads}")
                return applied
    
    def quit(self, fast=False):
        """停止引擎；应用退出时使用较短的fast收尾时限。"""
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    self._send_command('stop')
                    self._send_command('quit')
                    self.process.wait(timeout=0.25 if fast else 0.75)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=0.25 if fast else 0.75)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=0.25)
                except Exception:
                    try:
                        self.process.kill()
                    except (ProcessLookupError, OSError):
                        pass
                finally:
                    if self.process and self.process.poll() is None:
                        try:
                            self.process.kill()
                        except (ProcessLookupError, OSError):
                            pass
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

    def _go(
        self, search_limits: dict, timeout: float = 35,
        info_callback: Optional[Callable] = None,
    ) -> Tuple[List[str], str, List[dict]]:
        """
        发送go命令和读取结果
        """
        depth = search_limits['depth']
        movetime = search_limits['movetime']
        self._send_command(f"go depth {depth} movetime {movetime}")
        return self._read_output_with_timeout(timeout, info_callback)

    @staticmethod
    def parse_engine_info(output: str) -> dict:
        """解析UCI info行，供界面实时展示局势和搜索算力。"""
        if not output or not output.startswith('info '):
            return {}
        parts = output.split()
        result = {}

        def read_int(name):
            try:
                return int(parts[parts.index(name) + 1])
            except (ValueError, IndexError, TypeError):
                return None

        for key in ('depth', 'seldepth', 'nodes', 'nps', 'time'):
            value = read_int(key)
            if value is not None:
                result[key] = value

        if 'score' in parts:
            try:
                score_index = parts.index('score')
                score_type = parts[score_index + 1]
                score_value = int(parts[score_index + 2])
                if score_type in ('cp', 'mate'):
                    result['score_type'] = score_type
                    result['score'] = score_value
            except (ValueError, IndexError, TypeError):
                pass
        return result

    @staticmethod
    def resolve_search_limits(engine_params, depth_bonus=0, search_override=None):
        """同时解析深度和时间上限，任意条件先达到即结束搜索。"""
        try:
            base_depth = int(engine_params.get('depth', 20))
            bonus = max(0, int(depth_bonus))
        except (TypeError, ValueError):
            base_depth, bonus = 20, 0
        try:
            movetime = int(engine_params.get('movetime', 10000))
        except (TypeError, ValueError):
            movetime = 10000

        limits = {
            'depth': str(min(200, max(1, base_depth + bonus))),
            'movetime': str(min(600000, max(1, movetime))),
        }
        if search_override:
            param, value = str(search_override[0]), str(search_override[1])
            if param in limits:
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    parsed = int(limits[param])
                maximum = 200 if param == 'depth' else 600000
                limits[param] = str(min(maximum, max(1, parsed)))
        return limits

    def get_search_timeout(self, depth_bonus=0, search_override=None):
        """进程读取超时略大于引擎时间上限，仅用于异常兜底。"""
        limits = self.resolve_search_limits(
            context.get_engine_params(),
            depth_bonus,
            search_override,
        )
        try:
            movetime_seconds = int(limits['movetime']) / 1000.0
        except (TypeError, ValueError):
            movetime_seconds = 10.0
        minimum = 8.0 if search_override else 12.0
        margin = 5.0 if search_override else 10.0
        return min(620.0, max(minimum, movetime_seconds + margin))

    def get_bestmove(self, fen: str, side: bool, display_callback: Optional[Callable] = None, *, use_startpos: bool = True, is_newgame: bool = False, moves: Optional[str] = None, multipv: int = 1, depth_bonus: int = 0, search_override=None) -> Tuple[str, str, List[str]]:
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
            search_limits = self.resolve_search_limits(
                engine_params,
                depth_bonus,
                search_override,
            )
            search_timeout = self.get_search_timeout(depth_bonus, search_override)

            if display_callback:
                thinking_text = (
                    f"引擎正在计算（深度≤{search_limits['depth']} / "
                    f"时间≤{search_limits['movetime']}ms）..."
                )
                display_callback(Message(MessageType.STATUS, thinking_text))

            if is_newgame:
                self.new_game()

            self._position(fen_string, use_startpos=use_startpos, moves=moves)
            lines, best_move, pvs = self._go(
                search_limits, search_timeout, display_callback
            )

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
                    best_move = best_move[start_index:].split()[0][:4]
                    
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
    


    def _read_output_with_timeout(
        self, timeout: float = 1.0,
        info_callback: Optional[Callable] = None,
    ) -> Tuple[List[str], str, List[dict]]:
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
        last_info_emit = 0.0
        
        while time.time() - start_time < timeout:
            output = self.process.stdout.readline().strip()
            if output:
                lines.append(output)
                if output.startswith('info '):
                    telemetry = self.parse_engine_info(output)
                    now = time.monotonic()
                    if (
                        info_callback
                        and telemetry.get('depth') is not None
                        and now - last_info_emit >= 0.15
                    ):
                        info_callback(Message(
                            MessageType.ENGINE_INFO,
                            telemetry,
                            **telemetry,
                        ))
                        last_info_emit = now
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
