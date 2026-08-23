# JJ v2 数据采集与离线回放

新版 JJ 识别器使用独立数据会话，避免继续用旧 UI 模型反复调整阈值。
采集默认关闭，自动走子也默认关闭。

## 开启采集

在用户配置 `~/Library/Application Support/ChessHelper/game_config.json` 中加入或修改：

```json
"auto_move_enabled": false,
"jj_v2": {
  "recording_enabled": true,
  "record_unstable": true,
  "dataset_dir": ""
}
```

`dataset_dir` 留空时，数据写入：

```text
~/Library/Application Support/ChessHelper/jj_v2_datasets/<session-id>/
```

每次启动辅助会创建一个新会话。停止辅助时，后台写盘队列会被冲刷并关闭。
采集器会跳过与最后可信画面近似相同的空闲帧，只保留明显变化、动画和新稳定局面。采集线程只做 BGRA 字节复制，JPEG 编码在独立的有界后台线程执行；磁盘落后时会丢弃采集样本，不阻塞实时识别。

## 会话结构

```text
<session-id>/
├── session.json
├── manifest.jsonl
└── frames/
    ├── <frame-id>.jpg
    └── ...
```

`manifest.jsonl` 包含两种事件：

- `capture`：原始棋盘帧、时间戳、稳定状态、棋盘区域和图片路径。
- `analysis`：同一时间戳对应的棋盘数组、移动标记、规则状态与结算状态。

## 检查与回放

查看会话统计：

```bash
python -m app.chess.jj_v2 \
  "$HOME/Library/Application Support/ChessHelper/jj_v2_datasets/<session-id>"
```

代码中可直接读取与现有识别器兼容的 MSS 风格帧：

```python
from app.chess.jj_v2 import JJV2ReplayDataset

dataset = JJV2ReplayDataset("/path/to/session")
for frame in dataset.frames(stable_only=True):
    # frame.width / frame.height / frame.bgra
    pass
```

训练集、验证集和测试集必须按完整会话划分，不能把同一盘棋的相邻帧随机分散到不同集合。

## 生成棋子分类样本

```bash
python -m app.chess.jj_v2.build_dataset \
  "/path/to/output" \
  "/path/to/session-1" \
  "/path/to/session-2"
```

人工核对过的影子分歧可以通过 `--corrections corrections.jsonl` 覆盖伪标签。
每条修正必须包含会话、时间戳、行列、原标签和新标签；原标签不匹配或
修正没有实际命中时构建会失败，避免静默污染数据。
还可以使用 `--audit-model MODEL.onnx --audit-confidence 0.70` 进行教师审计：
高置信度冲突的非开局伪标签只写入 `quarantined_samples.jsonl`，不会自动
改标签或进入数据集；低置信度冲突仍保留，避免把教师模型猜测当作真值。

生成器会排除非法、多步和结算帧，并对近似重复的格子裁剪去重。标准开局使用规则模板作为 `start_template` 强标签；普通对局中的可信状态标为 `trusted_state` 伪标签，必须审计后再用于最终训练。
红黑棋子分别写入 `red_R`、`black_r` 等目录，避免 macOS 大小写不敏感文件系统将两个类别混在一起。

## 数据基线检查

在安装深度学习训练环境之前，可以先用现有 OpenCV/Numpy 做按整局留出的 HOG+kNN 诊断：

```bash
python -m app.chess.jj_v2.evaluate_baseline "/path/to/output"
```

它会生成 `baseline_metrics.json`、`baseline_errors.jsonl` 和 `baseline_knn.npz`。错误清单保留原图路径、棋盘位置、预期/预测类别和最近邻相似度。该模型仅用于发现标签污染、类别混淆和验证集覆盖不足，不会被自动部署为正式识别器。
## 训练候选 CNN

训练依赖与主程序依赖隔离。建议使用 Python 3.12 的独立环境：

```bash
python -m pip install -r requirements-train.txt
python -m app.chess.jj_v2.train_cnn DATASET_DIR OUTPUT_DIR \
  --holdout-games 5 6 --epochs 35 --balance-power 0.5
```

切分单位是完整对局，而不是随机图片。训练脚本使用类别均衡采样，输出
`best_model.pt`、`jj_v2_piece_model.onnx`、`jj_v2_piece_map.json` 和
`training_metrics.json`。这些文件默认都是候选产物，在独立 ONNX 推理和
整盘规则校验通过前，不应覆盖 `app/models/jj_piece_model.onnx`。
模型选择优先比较除走子标记外的棋盘类别准确率；现有规则链路可以容忍
标记缺失，这比把普通空位误判成标记更安全。

使用与主程序相同的 ONNX Runtime 独立复核指定对局：

```bash
python -m app.chess.jj_v2.evaluate_onnx DATASET_DIR MODEL_PATH \
  --games 5 6 --output /path/to/onnx_metrics.json
```

## 影子识别

“新版JJ影子识别（不走子）”会在独立线程运行候选 ONNX 模型，并将结果
写入 `~/Library/Application Support/ChessHelper/jj_v2_shadow/<session-id>/`。
影子模型不持有规则检查器、引擎、消息总线或鼠标控制器；其输出不会更新
正式棋盘，也不会触发推荐或点击。影子模式开启期间自动走子会被硬性禁用。

汇总一次影子会话：

```bash
python -m app.chess.jj_v2.report_shadow \
  "$HOME/Library/Application Support/ChessHelper/jj_v2_shadow/<session-id>"
```

如果实时影子会话因配置或启动问题中断，可从已采集会话确定性恢复：

```bash
python -m app.chess.jj_v2.replay_shadow \
  /path/to/jj_v2_dataset_session /path/to/model.onnx /path/to/shadow_output
```
