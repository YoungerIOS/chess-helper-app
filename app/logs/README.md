# 象棋助手日志系统

## 概述
象棋助手现在包含完整的日志记录系统，可以帮助用户在打包后排查问题。

## 日志文件位置
- 日志文件存储在 `logs/` 目录下
- 日志文件命名格式：`chess_helper_YYYYMMDD.log`
- 支持日志轮转，避免单个文件过大

## 日志级别
- **INFO**: 一般信息（默认级别）
- **WARNING**: 警告信息
- **ERROR**: 错误信息
- **DEBUG**: 调试信息

## 配置日志
可以通过修改 `json/log_config.json` 文件来自定义日志设置：

```json
{
    "log_level": "INFO",           // 日志级别
    "log_to_file": true,           // 是否写入文件
    "log_to_console": true,        // 是否输出到控制台
    "max_log_size_mb": 10,         // 单个日志文件最大大小（MB）
    "backup_count": 5,             // 保留的备份文件数量
    "log_format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "date_format": "%Y-%m-%d %H:%M:%S"
}
```

## 查看日志
### 方法1：直接查看文件
在 `logs/` 目录下找到对应的日志文件，用文本编辑器打开查看。

### 方法2：使用日志查看器
```python
from tools.log_viewer import LogViewer

# 创建日志查看器实例
viewer = LogViewer()

# 获取所有日志文件
log_files = viewer.get_log_files()

# 查看最新日志内容
if log_files:
    content = viewer.get_log_content(log_files[0])
    print(content)

# 搜索特定关键词
results = viewer.search_logs("错误")
for result in results:
    print(result)
```

## 常见问题排查

### 1. 程序启动失败
查看日志中的错误信息，通常包含：
- 配置文件读取失败
- 模型加载失败
- 权限问题

### 2. 功能异常
查看日志中的警告和错误信息：
- 棋子识别失败
- 引擎连接问题
- 平台切换失败

### 3. 性能问题
查看日志中的时间戳，分析：
- 模型加载时间
- 识别响应时间
- 配置保存时间

## 日志清理
系统会自动进行日志轮转，但也可以手动清理旧日志：

```python
from tools.log_viewer import LogViewer

viewer = LogViewer()
# 清理30天前的日志
deleted_count = viewer.clear_old_logs(30)
print(f"删除了 {deleted_count} 个旧日志文件")
```

## 注意事项
1. 日志文件会占用磁盘空间，建议定期清理
2. 生产环境中可以设置 `log_to_console: false` 减少输出
3. 调试时可以设置 `log_level: "DEBUG"` 获取更详细信息
4. 日志文件使用UTF-8编码，支持中文内容 