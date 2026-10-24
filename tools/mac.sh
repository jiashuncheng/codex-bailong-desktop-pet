#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$ROOT"
action="${1:-start}"
candidates=("${BAILONG_PYTHON:-}" "$ROOT/.venv/bin/python"
  "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
  /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13
  /usr/local/bin/python3.12 /usr/local/bin/python3.13
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3)
if command -v python3 >/dev/null 2>&1; then candidates+=("$(command -v python3)"); fi
for candidate in "${candidates[@]}"; do
  if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" -c 'import sys; sys.exit(not ((3,12)<=sys.version_info[:2]<(3,14)))' >/dev/null 2>&1; then
    exec "$candidate" "$ROOT/launch.py" "$action"
  fi
done
echo '未找到 Python 3.12 / 3.13。请从 https://www.python.org/downloads/macos/ 安装后重试。' >&2
exit 1
