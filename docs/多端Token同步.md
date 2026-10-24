# 多端 Token 同步

v0.9.5 / UI84。Windows、macOS 桌宠和无界面的 Linux 采集器，将可读 Codex 日志中的累计 Token 计数同步到私人汇总服务。程序不调用模型，也不额外消耗模型 Token。

## Windows / Mac 加入已有服务

1. 用 Git 更新到本仓库 main；旧工程先退出桌宠和 SSH 回传，再运行新工程的“一键启动”。
2. 在已连接的设备打开设置 → Codex → 多端 Token 同步，点击“导出另一台设备连接文件”。
3. 将 `.bailong-sync` 文件交给自己的另一台设备，在同一设置页点击“导入同步连接文件”。每份文件只能加入一台设备，7 天内有效。导入成功后启用同步并默认显示全部设备汇总。
4. 选择“显示本机统计”可仅切换显示口径，后台仍会同步。关闭同步后恢复本机统计。

设备不需要共享 Codex 登录、SSH 私钥或模型 API 密钥。连接文件包含短期配对凭据，应私下传递，不提交 Git。Mac 的访问凭据存系统钥匙串，Windows 用本用户 DPAPI；Linux 配置及数据目录权限为 0600 / 0700。设备访问密钥各不相同，可以在服务端单独撤销。

每 30 秒进行增量扫描与上报，手动刷新 Token 也会触发。桌宠关闭期间的日志会在下次运行时补传。第一次上报较多历史时分批处理，并显示“正在补传历史记录”。

## 去重与统计口径

- 从日志 `session_meta` 的会话 ID 生成稳定哈希，配合 `total_token_usage` 累计计数形成检查点；绝对路径、电脑名、文件复制和重命名不会产生新的消费。
- 服务端以“会话哈希＋累计 Token 数”唯一保存，按累计值重建增量。部分日志先到、完整日志晚到，只补充历史分布；总量不会再次相加。重复批次、网络回执丢失后重传也不会重复增加。
- 不同会话即使时间和计数相同也分别统计。同步文件被截断或以相同大小替换时会重读，已经确认的计数保留。
- 按 Codex 的会话累计计数口径统计；输入已包含缓存，输出已包含推理，不再次叠加。依赖日志记录的累计值，不能补出已丢失且从未采集的记录；不宣称是官方账单。旧版统计缓存中如果只剩汇总、原始日志已经删除，不会将无法可靠去重的旧汇总再次上传；同步范围为仍可读取的日志及已经形成的同步检查点。
- 同步仅上传会话哈希、UTC 时间、模型名、累计总量及输入/输出计数，不上传消息正文、指令、文件路径、账号或登录凭据。汇总服务不统计消息数，界面显示“未同步”。
- 日期和小时汇总统一为北京时间（Asia/Shanghai）。Token 卡片标为“全端”，日报标明多端去重来源。
- 离线时继续保留本地统计；已获取的多端汇总作为明确标记的离线缓存显示。首次连接失败且无缓存时，明确显示本机回退口径，不用本机数冒充全部设备数。
- 设备清单表示已加入同步服务的设备，不代表这些设备当前都在线，也不能将其各自原始总量直接相加。

仅有任务状态的 SSH 回传日志不含 Token 计数，不会凭空计入。远端 Token 由远端采集器直接读取真实日志并上报，与 SSH 状态回传分别运行。

## 服务端部署

服务端和 Linux 采集器只需要 Python 3.10+ 标准库。桌宠运行环境仍为 Python 3.12 / 3.13。

将仓库的 `app/` 与 `sync-service/` 放到服务器，确认已安装 Nginx 和 OpenSSL，以 root 从工程目录运行：

```bash
BAILONG_SYNC_HOST=你的域名或公网IP bash sync-service/install-server.sh
```

安装器建立低权限 `bailong-sync` 用户与 `bailong-token-sync.service`；API 仅监听 `127.0.0.1:8769`，由 Nginx 在 443 提供 TLS、请求大小限制和限速。现有 80 端口站点保留。需允许 ECS 安全组入站 TCP 443。

没有域名时使用带公网 IP SAN 的专用自签证书，通过连接文件分发公开证书；客户端严格验证证书链与主机名，不关闭 TLS 验证。服务端私钥仅留在服务器。不要直接将内部 Python HTTP 端口暴露公网。

状态与数据库：

- `/var/lib/bailong-token-sync/usage.sqlite3`：去重检查点、派生统计、设备密钥的哈希、短期配对码的哈希。
- `/etc/bailong-token-sync/`：TLS 证书与私钥。
- `/opt/bailong-token-sync/current/app/`：服务源码。
- `systemctl status bailong-token-sync` / `journalctl -u bailong-token-sync`：服务状态。

首次设备可由管理员签发（结果包含凭据，直接写入权限受限文件，不贴到公开日志）：

```bash
umask 077
runuser -u bailong-sync -- python3 /opt/bailong-token-sync/current/app/token_sync_server.py \
  --db /var/lib/bailong-token-sync/usage.sqlite3 --create-device 设备名称 > /root/device-access.json
```

其后的设备通过已连接桌宠导出配对文件加入。撤销设备时停止对应客户端，并在服务端数据库 `devices` 表删除该设备 ID；失效密钥将不能读取或上传。

## Linux 采集器

把同一份源码放到远端，在私有状态目录准备 `token-sync.json`，包含 `enabled`、`url`、公开 `ca`、该设备独立的 `device_id` 与 `token`。`home` 指向真正运行 Codex 的用户数据目录。

```bash
python3 sync-service/agent.py --state ~/.local/share/bailong-token-agent/state --home ~/.codex
```

可注册为该用户的 systemd 服务自动运行；本次实际部署使用 `bailong-token-agent.service`。不会安装图形库，不改动 Codex 本身。

## 更新、备份与验证

源码更新保留服务端数据库和每台设备的私有配置。服务端更新需上传新源码后重启服务；桌宠 Git 更新不会远程擅自改写服务器。备份数据库使用 SQLite backup 接口或在线备份命令，避免只复制运行中的主文件而遗漏 WAL。

```bash
python -m unittest discover -s app -p test_token_sync.py
python tools/check_source.py --without-assets
```

测试覆盖：跨端副本去重、乱序/部分历史、重试与游标确认、文件截断和替换、离线缓存、配对单次使用、无关字段拒绝。CI 不访问真实服务、钥匙串或账号。
