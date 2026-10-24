#!/bin/bash
ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
/bin/bash "$ROOT/tools/mac.sh" check
result=$?
if [[ $result -ne 0 ]]; then
  echo "操作未完成，请查看上方提示。按回车关闭窗口。"
  read -r _
fi
exit "$result"
