#!/bin/bash
# Run as root from the uploaded source directory. Never print credentials.
set -euo pipefail
: "${BAILONG_SYNC_HOST:?Set the public IP or DNS hostname}"
SOURCE_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
if [[ $(id -u) != 0 ]]; then echo 'Run as root.' >&2; exit 1; fi
command -v nginx >/dev/null
command -v openssl >/dev/null
if ! id bailong-sync >/dev/null 2>&1; then useradd --system --home-dir /var/lib/bailong-token-sync --shell /usr/sbin/nologin bailong-sync; fi
install -d -o bailong-sync -g bailong-sync -m 700 /var/lib/bailong-token-sync
install -d -m 755 /opt/bailong-token-sync/current/app
for source_file in token_sync_server.py token_calendar.py token_analytics.py sync_ledger.py token_sync.py log_catalog.py performance_metrics.py; do
  install -m 644 "$SOURCE_ROOT/app/$source_file" "/opt/bailong-token-sync/current/app/$source_file"
done
install -d -m 700 /etc/bailong-token-sync
if [[ ! -e /etc/bailong-token-sync/server.crt ]]; then
  if [[ "$BAILONG_SYNC_HOST" =~ ^[0-9.]+$ ]]; then san="IP:$BAILONG_SYNC_HOST"; else san="DNS:$BAILONG_SYNC_HOST"; fi
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout /etc/bailong-token-sync/server.key -out /etc/bailong-token-sync/server.crt -subj "/CN=$BAILONG_SYNC_HOST" -addext "subjectAltName=$san" > /dev/null 2>&1
  chmod 600 /etc/bailong-token-sync/server.key
fi
cat > /etc/systemd/system/bailong-token-sync.service <<'EOF'
[Unit]
Description=Bailong cross-device token accounting
After=network.target
[Service]
Type=simple
User=bailong-sync
Group=bailong-sync
Environment=TZ=Asia/Shanghai
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/python3 /opt/bailong-token-sync/current/app/token_sync_server.py --db /var/lib/bailong-token-sync/usage.sqlite3
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/bailong-token-sync
UMask=0077
MemoryMax=256M
[Install]
WantedBy=multi-user.target
EOF
conf=/etc/nginx/conf.d/bailong-token-sync.conf
if [[ -e "$conf" ]] && ! head -1 "$conf" | grep -q '^# Bailong Token Sync managed'; then echo 'Refusing to overwrite unmanaged nginx configuration.' >&2; exit 1; fi
cat > "$conf" <<EOF
# Bailong Token Sync managed
limit_req_zone \$binary_remote_addr zone=bailong_token_sync:1m rate=10r/s;
server {
    listen 443 ssl;
    server_name $BAILONG_SYNC_HOST;
    ssl_certificate /etc/bailong-token-sync/server.crt;
    ssl_certificate_key /etc/bailong-token-sync/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 1m;
    client_body_timeout 15s;
    access_log off;
    location / {
        limit_req zone=bailong_token_sync burst=20 nodelay;
        proxy_pass http://127.0.0.1:8769;
        proxy_set_header Host \$host;
        proxy_set_header Connection "";
        proxy_read_timeout 30s;
        proxy_connect_timeout 3s;
    }
}
EOF
nginx -t
systemctl daemon-reload
systemctl enable --now bailong-token-sync
systemctl restart bailong-token-sync
systemctl reload nginx
printf 'Token sync service installed. API binds to 127.0.0.1:8769; TLS is provided by nginx.\n'
