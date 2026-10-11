import os
import re
import sys
import uuid
import json
import shutil
import threading
import subprocess
import time
import requests
from typing import Optional, Callable
from app.tools.log_config import get_logger
from app.tools.utils import app_data_path, resource_path

logger = get_logger(__name__)

class TunnelManager:
    """Cloudflare Tunnel 管理器，负责生命周期管理、公网域名捕获和配对码同步"""
    
    def __init__(self, local_port: int = 5050):
        self.local_port = local_port
        self.process: Optional[subprocess.Popen] = None
        self.tunnel_url: Optional[str] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.on_url_ready: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        
        # 加载或生成永久固定的设备配对码 (Pairing ID)
        self.pairing_id = self._get_or_create_pairing_id()

    def _get_or_create_pairing_id(self) -> str:
        """获取或创建本机专属的永久配对码"""
        id_file = app_data_path("pairing_id.txt")
        try:
            if os.path.exists(id_file):
                with open(id_file, "r", encoding="utf-8") as f:
                    pid = f.read().strip()
                    if pid:
                        return pid
        except Exception:
            pass

        # 生成形如 CHESS-8F3A 的简短固定配对码
        new_pid = f"CHESS-{uuid.uuid4().hex[:6].upper()}"
        try:
            with open(id_file, "w", encoding="utf-8") as f:
                f.write(new_pid)
        except Exception as e:
            logger.error(f"Failed to save pairing ID: {e}")
        return new_pid

    @staticmethod
    def get_cloudflared_path() -> Optional[str]:
        """寻找 cloudflared 二进制路径 (支持内置、App数据目录和系统PATH)"""
        # 1. 优先使用项目内置路径 (随软件一起分发，如 app/bin/cloudflared)
        bundled = resource_path("bin", "cloudflared")
        if os.path.isfile(bundled) and os.access(bundled, os.X_OK):
            return bundled
            
        # 2. 检查用户数据目录 (自动下载的缓存路径)
        data_path = app_data_path("bin", "cloudflared")
        if os.path.isfile(data_path) and os.access(data_path, os.X_OK):
            return data_path

        # 3. 查找系统 PATH
        found = shutil.which("cloudflared")
        if found:
            return found
        
        # 4. 常见 macOS 安装路径 (Homebrew 等)
        candidates = [
            "/opt/homebrew/bin/cloudflared",
            "/usr/local/bin/cloudflared",
            os.path.expanduser("~/bin/cloudflared"),
        ]
        for c in candidates:
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def download_cloudflared(self, progress_callback: Optional[Callable[[str], None]] = None) -> Optional[str]:
        """在本地没有该组件时，自动静默下载并解压 (约18MB)，免除用户任何终端操作"""
        import platform
        import tarfile
        import urllib.request
        
        target_dir = app_data_path("bin")
        os.makedirs(target_dir, exist_ok=True)
        target_bin = os.path.join(target_dir, "cloudflared")
        
        arch = "arm64" if platform.machine() in ["arm64", "aarch64"] else "amd64"
        download_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-{arch}.tgz"
        tar_path = os.path.join(target_dir, "cloudflared.tgz")
        
        logger.info(f"Downloading cloudflared from {download_url}...")
        if progress_callback:
            progress_callback("正在自动下载穿透组件 (约18MB)...")
            
        try:
            # 下载 tgz 压缩包 (Cloudflare 官方单文件二进制发布包)
            urllib.request.urlretrieve(download_url, tar_path)
            
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=target_dir)
                
            if os.path.exists(tar_path):
                os.remove(tar_path)
                
            os.chmod(target_bin, 0o755)
            logger.info(f"cloudflared successfully auto-installed to {target_bin}")
            return target_bin
        except Exception as e:
            logger.error(f"Failed to auto-download cloudflared: {e}")
            if os.path.exists(tar_path):
                try: os.remove(tar_path)
                except: pass
            return None

    def start(self, on_url_ready: Optional[Callable[[str], None]] = None, on_error: Optional[Callable[[str], None]] = None):
        """异步启动隧道服务"""
        if self.is_running:
            if self.tunnel_url and on_url_ready:
                on_url_ready(self.tunnel_url)
            return

        self.on_url_ready = on_url_ready
        self.on_error = on_error
        self.is_running = True
        self.tunnel_url = None

        self._thread = threading.Thread(target=self._run_tunnel_worker, daemon=True)
        self._thread.start()

    def _run_tunnel_worker(self):
        """后台寻找或自动静默下载 cloudflared 并启动"""
        bin_path = self.get_cloudflared_path()
        if not bin_path:
            bin_path = self.download_cloudflared(progress_callback=self.on_error)
            
        if not bin_path:
            err_msg = "未检测到 cloudflared 组件，且自动下载未成功。请检查网络连接或运行: brew install cloudflared"
            logger.error(err_msg)
            self.is_running = False
            if self.on_error:
                self.on_error(err_msg)
            return

        self._run_tunnel(bin_path)

    def _run_tunnel(self, bin_path: str):
        """后台运行 cloudflared 进程并实时正则解析输出 URL"""
        cmd = [
            bin_path, "tunnel",
            "--protocol", "http2",
            "--edge-ip-version", "4",
            "--ha-connections", "1",
            "--no-autoupdate",
            "--url", f"http://127.0.0.1:{self.local_port}"
        ]
        logger.info(f"Starting tunnel: {' '.join(cmd)}")
        
        try:
            # cloudflared 会将日志输出到 stderr
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # 正则匹配形如 https://xxx.trycloudflare.com 的 URL
            pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            
            while self.is_running and self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if not line:
                    break
                
                # 寻找匹配的临时域名
                match = pattern.search(line)
                if match and not self.tunnel_url:
                    self.tunnel_url = match.group(0)
                    logger.info(f"Captured Cloudflare Tunnel URL: {self.tunnel_url}")
                    
                    # 异步向免费云端同步节点汇报最新外网地址
                    threading.Thread(target=self._sync_to_cloud, args=(self.tunnel_url,), daemon=True).start()
                    
                    if self.on_url_ready:
                        self.on_url_ready(self.tunnel_url)
                        
            # 如果异常退出且没获取到 URL
            if self.is_running and not self.tunnel_url:
                err = "Cloudflare 隧道异常终止，未能获取公网 URL"
                logger.error(err)
                if self.on_error:
                    self.on_error(err)

        except Exception as e:
            logger.error(f"Tunnel process exception: {e}")
            if self.on_error:
                self.on_error(str(e))
        finally:
            self.is_running = False

    def _sync_to_cloud(self, url: str):
        """将配对码和公网 URL 同步到公共中继存储 (dweet.io，无需任何账号)"""
        sync_url = f"https://dweet.io/dweet/for/{self.pairing_id}"
        payload = {
            "pairing_id": self.pairing_id,
            "wan_url": f"{url}/api/analyze",
            "updated_at": int(time.time())
        }
        try:
            resp = requests.post(sync_url, json=payload, timeout=5)
            if resp.status_code == 200:
                logger.info(f"Pairing info successfully synced to cloud for {self.pairing_id}")
            else:
                logger.warning(f"Cloud sync status {resp.status_code}")
        except Exception as e:
            logger.warning(f"Cloud sync failed (non-critical): {e}")

    def stop(self):
        """停止隧道进程"""
        self.is_running = False
        self.tunnel_url = None
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        logger.info("Cloudflare Tunnel stopped")
