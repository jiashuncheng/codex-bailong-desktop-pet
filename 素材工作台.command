#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo 'Please run the desktop source dependency installer first.'
  exit 1
fi
exec .venv/bin/python tools/material_workbench/启动.py
