#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo 'Please run the desktop source dependency installer first.'
  exit 1
fi
.venv/bin/python -m pip install -r tools/material_workbench/requirements-matting.txt
exec .venv/bin/python tools/material_workbench/download_models.py
