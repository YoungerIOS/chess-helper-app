import os
import glob
from datetime import datetime
from typing import List, Optional

class LogViewer:
    """日志查看器工具类"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
    
    def get_log_files(self) -> List[str]:
        """获取所有日志文件"""
        if not os.path.exists(self.log_dir):
            return []
        
        pattern = os.path.join(self.log_dir, "chess_helper_*.log*")
        log_files = glob.glob(pattern)
        return sorted(log_files, reverse=True)  # 最新的文件在前
    
    def get_log_content(self, log_file: str, max_lines: int = 1000) -> str:
        """获取指定日志文件的内容"""
        if not os.path.exists(log_file):
            return f"日志文件不存在: {log_file}"
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            if len(lines) <= max_lines:
                return ''.join(lines)
            else:
                # 只返回最后max_lines行
                return ''.join(lines[-max_lines:])
        except Exception as e:
            return f"读取日志文件失败: {str(e)}"
    
    def get_log_stats(self, log_file: str) -> dict:
        """获取日志文件统计信息"""
        if not os.path.exists(log_file):
            return {"error": "文件不存在"}
        
        try:
            stat = os.stat(log_file)
            file_size = stat.st_size
            modified_time = datetime.fromtimestamp(stat.st_mtime)
            
            # 统计日志级别
            level_counts = {"INFO": 0, "WARNING": 0, "ERROR": 0, "DEBUG": 0}
            
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    for level in level_counts.keys():
                        if f" - {level} - " in line:
                            level_counts[level] += 1
                            break
            
            return {
                "file_size": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2),
                "modified_time": modified_time.strftime("%Y-%m-%d %H:%M:%S"),
                "level_counts": level_counts,
                "total_lines": sum(level_counts.values())
            }
        except Exception as e:
            return {"error": str(e)}
    
    def clear_old_logs(self, days_to_keep: int = 30) -> int:
        """清理旧日志文件，返回删除的文件数量"""
        if not os.path.exists(self.log_dir):
            return 0
        
        cutoff_time = datetime.now().timestamp() - (days_to_keep * 24 * 3600)
        deleted_count = 0
        
        for log_file in self.get_log_files():
            try:
                if os.path.getmtime(log_file) < cutoff_time:
                    os.remove(log_file)
                    deleted_count += 1
            except Exception:
                pass
        
        return deleted_count
    
    def search_logs(self, keyword: str, log_file: Optional[str] = None) -> List[str]:
        """在日志中搜索关键词"""
        results = []
        
        if log_file:
            files_to_search = [log_file] if os.path.exists(log_file) else []
        else:
            files_to_search = self.get_log_files()
        
        for file_path in files_to_search:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        if keyword.lower() in line.lower():
                            results.append(f"{os.path.basename(file_path)}:{line_num}: {line.strip()}")
            except Exception:
                continue
        
        return results 