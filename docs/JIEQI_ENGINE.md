# 揭棋引擎说明

本项目的揭棋协议适配依据 Pikafish 官方仓库 `jieqi` 分支；截至接入时，
该分支提交为 `9b963f727983a1d9308e0dca48b39c802b8e75a2`，但没有可用的揭棋 NNUE。

本地可执行文件 `app/Pikafish/PikaJieQi` 因此由同一官方仓库的
`jieqi_old` 分支提交 `23b9466c981f0f3a1133f92de1a6f86406c4eccc` 编译，目标为
macOS Apple Silicon（arm64）。该版本使用手工评估并已通过 UCI 搜索冒烟测试。

Pikafish 采用 GNU GPL v3 许可证。源码与许可证：

- https://github.com/official-pikafish/Pikafish/tree/jieqi
- https://github.com/official-pikafish/Pikafish/tree/jieqi_old
- https://github.com/official-pikafish/Pikafish/blob/jieqi_old/Copying.txt

揭棋历史着法格式：普通着法为四位坐标；暗子移动后，第五位记录揭示棋种；
若同时掌握被吃暗子的真实身份，第六位可记录该棋种。助手目前从棋盘画面记录
第五位；无法从静态棋盘获知的暗子被吃身份保持未知，由引擎按未知信息处理。
