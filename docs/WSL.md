# 接入 WSL 内的 Codex

对应 [Issue #6](https://github.com/Wunsch2048/codex-bailong-desktop-pet/issues/6)。这是 Windows 桌宠连接本机 WSL 内的 Codex，不是 Linux 原生桌宠版本。公开程序补丁包 1.0.1 已加入此接入方式；旧版 v1.0.0 不包含 WSL 接入。实机验证边界见本文末尾。

## 设置

1. 打开设置的 Codex 页，展开“连接路径与检测报告”。
2. 连接来源选 WSL，点击“刷新发行版”，选择已安装的发行版。
3. Linux 用户留空使用默认用户；数据目录留空从 Linux CODEX_HOME 或 $HOME/.codex 识别。CLI 留空从 Linux PATH、NVM 和常见 VS Code Server 扩展位置识别，也可填写绝对 Linux 路径。不要填写 Windows .exe。
4. 点击“验证并保存路径”。验证会启动所选发行版，检查 Linux CLI 版本和 Windows 共享目录的可读性。
5. 重启桌宠。当前进程继续使用原来源，防止保存配置过程中混入另一个账户的数据。

一次选择一个来源，不同时汇总 Windows 和多个发行版。Windows 原来的路径会保留，切回 Windows 后可继续使用。Windows 下的 CODEX_HOME 不覆盖所选 Linux 目录；登录与代理等使用 Linux 登录环境，不复制 Windows 登录文件。

## 能力与边界

- 从 WSL 文件共享读取会话日志、任务状态、完成提醒、Token 与额度周期记录。
- 在所选发行版/用户内调用 Linux Codex app-server，只读取账户额度，不发送聊天。
- 点击会话在 Windows Terminal 或独立控制台运行 Linux codex resume，使用该来源的 CODEX_HOME。
- Linux 路径区分大小写。不同发行版/数据目录分别建立本机统计索引、完成提醒和本机重置证据；不迁入旧 Windows 统计。
- WSL 不接入 Windows Codex 桌面实时管道和自动已读。部分细分状态以日志能提供的内容为准，完成提醒可手动确认。
- 随 Windows Codex 桌面端启动的设置仍专指 Windows 桌面端。WSL 进程启动/退出联动未实现；WSL 来源不会因 Windows Codex 关闭而退出。
- 所选发行版未运行时提示不可用并保留旧数据，后台不自动改用 Windows 账户。不会自动安装 WSL 或发行版。

跨系统路径与命令调用参考 [Microsoft WSL 文件系统说明](https://learn.microsoft.com/en-us/windows/wsl/filesystems) 和 [WSL 命令](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)。

## 性能与验证

默认 Windows 来源不枚举 WSL。UNC 路径不在界面启动时 resolve；目录验证、发行版查询和额度查询在后台；运行状态短缓存避免高频创建进程，CLI 调用前重新检查运行状态。关闭时等待路径/连接任务采用完成信号，不在 GUI 线程等待数秒。

本机没有安装 WSL，因此发行版内的真实登录、UNC 共享和真实额度查询尚未实机验收。已验证适配器、路径大小写/来源隔离、命令参数、RPC 传输夹具、停止状态、设置保存及 Windows 实际界面；不能把这些称为 WSL 实机通过，也不应仅据此关闭 issue。
