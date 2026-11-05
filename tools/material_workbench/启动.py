"""Use the existing desktop-pet Python environment on each platform."""
from pathlib import Path
import os,sys,importlib.util
from config_store import load_config
BASE=Path(__file__).resolve().parent
if importlib.util.find_spec('PySide6') is None:
    cfg=load_config(BASE/'配置.json');candidate=Path(cfg.get('python',sys.executable))
    if candidate.is_file() and not os.environ.get('BAILONG_WORKBENCH_BOOTSTRAPPED'):
        os.environ['BAILONG_WORKBENCH_BOOTSTRAPPED']='1'
        os.execv(str(candidate),[str(candidate),str(BASE/'启动.py')])
    raise SystemExit('没有找到PySide6。请用白龙桌宠源码目录内的Python运行本文件，或按跨平台说明安装依赖。')
from workbench import main
raise SystemExit(main())
