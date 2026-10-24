# 跨平台源码开发

Windows / macOS 运行入口为 `run_source.py`，日常启动使用 `launch.py` 或对应的一键脚本。Python 3.12 / 3.13，运行依赖见 `requirements-source.txt`。使用方式、素材与同步说明见 [跨平台源码使用](跨平台源码使用.md)。下文保留 Windows 冻结构建流程；该流程的打包和实机验证需单独执行。

# 开发与构建

Windows x64，Python 3.12（当前本地冻结环境为3.12.14）。先安装 requirements-enhanced.txt，所有命令从仓库根目录执行。原项目与授权边界见根目录 NOTICE.md。

## 准备动画

Git不保存大型动画。安装正式版本后，在设置中下载高清素材，再执行 `python tools/import_installed_assets.py`：工具验证并导入高清源和循环接缝，不读取账户、聊天或统计。也可以从 materials Release 下载高清ZIP，解压到 `outputs/白龙桌宠素材/`，其下应直接存在素材清单和quality各目录。不要把512px轻量素材冒充720px构建源。

当前共有25个逻辑动作和6段循环接缝。导入工具支持 `--source` 指向已解压高清目录或含outputs目录的旧高清程序。旧历史质量回归另需原始开发帧；发布播放素材不能替代全部历史夹具。

## 本地迭代

`python app/enhanced.py` 运行源码；会使用本用户桌宠数据，测试请隔离LOCALAPPDATA/CODEX_HOME，避免与正在运行的正式程序混用。

`python build_local.py --build-only` 完整检查并构建应用目录；`python build_local.py --deploy-verified` 实装刚验证且源码未变的构建，备份用户数据并保留回退。默认不生成公开安装器或ZIP。完整历史回归需要开发素材和夹具，干净仓库不能宣称全量708项都可直接运行。

最终EXE另做离线TLS初始化自检，要求证书和主机名校验开启。构建工具会保留解释器SSL实现依赖的附属数据文件；不要用关闭验证来替代补齐运行依赖。

`python build_release.py` 仅构建应用目录，不改变本机安装。公开发布时显式运行 `python build_release.py --package`，生成默认轻量载荷、程序小包及一键部署EXE；完整Windows下载ZIP还需加入部署文档并验证。`python check_bundle.py` 比对编译模块。输出与缓存不提交Git。

程序小包只省略明确匹配的动画素材，所有程序/运行库/字体来自新包。软件Release须同时提供完整Windows ZIP、program.zip、program.json、合并SHA256SUMS；旧客户端首次迁移、新安装及素材不兼容使用完整包。高清按内容ID单独发布为预发布且不设Latest，不能让资源标签取代软件稳定版。

## 不依赖外部动画的检查

在PowerShell设置 `$env:PYTHONPATH='app'` 与 `$env:QT_QPA_PLATFORM='offscreen'`，然后运行 `.github/workflows/checks.yml` 中列出的unittest模块。CI使用相同入口并编译检查app与tools；涉及真实桌面、安装、历史素材及浏览器的验收另行运行。

## 关键模块

| 模块 | 作用 |
| --- | --- |
| desktop / enhanced | 人物、卡片、后台服务与生命周期 |
| stream_player / sustained_player / decode_runtime / loop_cache | 有界解码、共用中段和尾部读取、高精度帧时钟、异步取消及压缩循环缓存 |
| continuous_work / status_reactions | 稳定语义与主会话优先、完整尾部和完成优先 |
| compact_bubble / surface_morph / linked_report_motion | 胶囊、卡片和日报原生交接 |
| token_analytics / daily_report | 增量统计、小时/模型与日报 |
| material_store / material_controller | 轻量默认、高清校验和安全切换 |
| app_updates / program_updates / program_update_apply | 完整/程序更新、素材兼容检查、事务安装与回退 |
| installer / deployment_state / shared_assets | nonce就绪、用户数据备份、入口切换与素材复用 |

人物帧时钟使用perf_counter，业务状态保留monotonic，不能混算绝对值。取消只发停止信号，GUI不等待旧解码线程；每个生产者独立队列，旧任务不可发布新缓存。24MiB只是压缩循环缓存预算，不是进程总内存。

## 高清资源构建

可本地运行 `python build_materials.py --package-hd`，会验证源帧并生成独立资源ZIP。仓库还提供手动触发的Publish HD materials工作流：读取已公开且固定SHA的v0.7.2基包、当前素材清单及六段已验证接缝输入；把旧安装器当数据读取，不执行它。每个素材逐一校验，最终ZIP需与本地规范组装SHA一致，上传完整后再公开资源预发布，不修改稳定Latest。此工作流只针对当前内容版本；后续换源须重新评审和验证。

书本等量工具额外需要tiktoken；应用本身不打包整本书或tokenizer。不得提交凭据、真实会话、日志、用户数据库、运行配置或安装器。
