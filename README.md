# 白龙桌宠 · Windows / macOS 兼容个性化版

![白龙桌宠](docs/media/cover.png)

在 Windows 和 Mac 上使用同一份 Python 源码，查看 Codex 任务状态、接收完成提醒、统计额度与 Token，并与白龙互动。保留源码和一键执行脚本，方便后续修改、更新及两端同步。

**当前版本：v0.9.4 / UI83**。已合入 [Wunsch2048 增强版](https://github.com/Wunsch2048/codex-bailong-desktop-pet) 的 v0.9.3 及其后构建修复，基线提交 `76a2ee3`；同时保留本仓库的个性化功能和 Mac 适配。角色与原始桌宠来自 [jingh12312-rgb/bailong-desktop-pet](https://github.com/jingh12312-rgb/bailong-desktop-pet)。

[源码使用与更新](docs/跨平台源码使用.md) · [上游 v0.9.3 更新](docs/releases/v0.9.3.md) · [来源与授权](NOTICE.md) · [反馈问题](https://github.com/jiashuncheng/codex-bailong-desktop-pet/issues)

## 本仓库新增与保留的自定义功能

| 功能 | 说明 |
| --- | --- |
| Windows / macOS 共用源码 | 通用界面、动画、会话和统计共用 `app/`，系统接口按平台适配；两端均提供一键启动、停止、检查和同步脚本 |
| Mac 窗口焦点修复 | 人物与普通状态卡片不取得键盘焦点，避免干扰其他窗口打字和快捷键；主动打开设置或聊天时才接收输入 |
| 多会话自动轮换 | 状态区保留两条会话，默认每 6 秒轮换；鼠标悬停或滚动时暂停，可调整间隔或关闭 |
| SSH 远程状态回传 | 通过本机已配置的 OpenSSH 别名读取远端 Codex 状态，展示远程任务、完成提醒和会话名称；保留远端标题与重命名修复 |
| 点击人物随机动作 | 主动点击时，从全部 25 个逻辑动作中等概率选择，保留原有播放边界与声音规则 |
| 本地高清素材接入 | 导入已下载的 720px 高清包，逐文件校验并建立独立快照；有完整轻量素材时支持部分高清回退，补齐后再次更新即可 |
| Mac 系统集成 | 适配应用发现、登录启动、系统钥匙串、菜单栏及基于辅助功能的视频全屏让位 |
| 安全同步源码 | 从本人的 fork 快进更新；工作区有未提交修改或历史分叉时停止，避免覆盖本地修改；更新后自动重启 |

## 已合入的上游新功能

- **v0.9.3 状态图标**：三颗水球旋转、交错和短暂黏连；浅色卡片与深色胶囊使用适配配色，状态切换连续变形。
- **持续工作动作改进**：修正循环期间笔记本反复开合，保留状态改变后的自然收尾。
- **字体与闲聊改进**：随源码携带 Noto Sans SC 和 Chakra Petch；改进聊天配置保存、服务校验、SSE/JSON 响应和错误提示。
- **设置整理与面板分离**：六类设置页，人物和面板可分别拖动；保留额度重置、完成提醒、Token 统计、日报和胶囊快捷入口等功能。
- **Windows 联动与维护**：保留随 Codex 启动、Codex 退出联动及上游安装维护修复。Mac 当前支持登录自启，Codex 启停监听选项暂不可用。

上游发行说明中的 Windows 冻结安装包与实机验收记录属于上游版本。本仓库主要交付可修改源码及脚本，源码维护使用本 fork 的 Git 更新流程。

## 快速开始

需要 **Python 3.12 或 3.13**；使用源码同步另需 Git。两台电脑分别克隆，各自建立环境。

```bash
git clone https://github.com/jiashuncheng/codex-bailong-desktop-pet.git
cd codex-bailong-desktop-pet
```

| 操作 | Windows | macOS |
| --- | --- | --- |
| 启动 / 修改后重启 | `一键启动.cmd` | `一键启动.command` |
| 停止桌宠及 SSH 回传 | `停止桌宠.cmd` | `停止桌宠.command` |
| 打开设置 | `打开设置.cmd` | `打开设置.command` |
| 准备运行环境 | `安装或修复依赖.cmd` | `安装或修复依赖.command` |
| 检查源码 | `检查源码版本.cmd` | `检查源码版本.command` |
| 同步仓库更新 | `同步更新源码.cmd` | `同步更新源码.command` |
| 更新已下载的高清素材 | `更新本地高清素材.cmd` | `更新本地高清素材.command` |

首次启动自动创建工程内 `.venv` 并安装对应系统依赖，需要联网。Mac 若提示脚本没有执行权限，可在工程目录运行 `chmod +x *.command`，再双击启动。

### 动画素材

Git 不保存大型动画。首次没有素材时，启动脚本会提示选择已有的完整高清素材目录，其下应直接包含 `素材清单.json` 和 `quality-*` 子目录。例如旧工程中的 `materials/hd/内容ID/`。已有校验通过的本机缓存可复用。

也可使用 [上游高清资源发布](https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases) 的匹配素材包。角色画质可在设置中切换。素材与程序分开更新，高清源补齐后运行“更新本地高清素材”重新校验、接入并重启。

### Codex 与 SSH

先在本机安装、登录并使用 Codex。没有状态时，在设置的 Codex 页检测连接，必要时选择本机 CLI 与数据目录。

远程会话在同一页的 SSH 区域配置：使用本机能够免交互连接的 SSH 别名，远端 Linux 需要 `python3`。SSH 只回传远端会话状态，不把远端状态冒充本机 Token 用量；SSH 密钥与认证由各台电脑自行配置。

## 两端更新与自定义开发

日常使用 `main` 分支。修改后先检查、提交并推送到本 fork，另一台运行“同步更新源码”。脚本只允许干净工作区上的快进更新；本地修改未提交或两端提交分叉时，需要先自行提交、合并。

GitHub 的“Sync fork”不是本工程的个性化合并流程。需要新增上游功能时，先合并上游，再验证 Windows / Mac，保留本仓库的系统适配与自定义功能。

用户数据分别保存在：

- Windows：`%LOCALAPPDATA%/BailongEnhanced`
- macOS：`~/Library/Application Support/BailongMac`

源码更新保留本机设置、聊天、统计与素材缓存。环境、认证、API 密钥、SSH 配置、日志与会话内容均不通过 Git 同步。从旧源码目录迁移时，先用旧工程的停止脚本退出桌宠和 SSH 回传，再启动本工程。

## 验证与已知范围

```bash
python tools/check_source.py --without-assets
python tools/check_source.py --require-assets
```

第一条运行不依赖外部动画的检查；第二条额外校验完整轻量素材及相关界面测试。GitHub Actions 对 Windows / macOS 分别检查源码运行环境，Windows 冻结构建相关逻辑另设检查任务。Mac 原生窗口与焦点使用隔离的 `tools/mac_ui_probe.py`、`tools/mac_focus_probe.py` 验证。

自动测试不等同于所有系统、缩放、浏览器和播放器的实机验收。Mac 视频全屏识别需要辅助功能权限；Mac 的 Codex 启停监听尚未实现。额度与会话状态取决于本机 Codex 数据及接口兼容情况。

## 来源与授权

感谢 [Wunsch2048 的增强版本](https://github.com/Wunsch2048/codex-bailong-desktop-pet) 和 [jingh12312-rgb 的原项目](https://github.com/jingh12312-rgb/bailong-desktop-pet)。本仓库在其基础上添加跨平台适配和个人定制，保留来源、素材声明及第三方组件许可证。

原项目未提供覆盖全工程的统一开源许可证；仓库公开不代表自动获得商业使用或任意再分发授权。具体边界请阅读 [NOTICE.md](NOTICE.md) 与 [原素材说明](docs/upstream/ASSETS.md)。本项目与 OpenAI、Codex 官方无隶属关系。
