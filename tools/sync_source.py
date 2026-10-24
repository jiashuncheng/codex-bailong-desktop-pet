"""Fast-forward this fork's tracked branch without discarding local edits."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
ALLOWED_REPO='jiashuncheng/codex-bailong-desktop-pet'

def git(*args,check=True):
    return subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',check=check)

def main():
    if git('status','--porcelain').stdout.strip():
        raise RuntimeError('本地有未提交的源码修改，请先提交或自行保存；同步不会覆盖这些修改。')
    remote=git('remote','get-url','origin').stdout.strip()
    normalized=remote.removesuffix('.git').replace('git@github.com:','https://github.com/').rstrip('/')
    if normalized!='https://github.com/'+ALLOWED_REPO:
        raise RuntimeError('origin 不是配置的个人 fork，请先确认仓库地址。')
    branch=git('symbolic-ref','--quiet','--short','HEAD').stdout.strip()
    git('fetch','origin',branch)
    if git('merge-base','--is-ancestor','HEAD','FETCH_HEAD',check=False).returncode:
        raise RuntimeError('本地与远程分支已分叉，请先合并修改；同步不会强制覆盖或重置分支。')
    if git('rev-parse','HEAD').stdout==git('rev-parse','FETCH_HEAD').stdout:
        print('源码已是远程当前版本。');return 0
    subprocess.run([sys.executable,str(ROOT/'launch.py'),'stop'],check=True)
    try:
        git('merge','--ff-only','FETCH_HEAD')
    finally:
        subprocess.run([sys.executable,str(ROOT/'launch.py'),'start'],check=True)
    print('源码已同步，桌宠已重新启动。');return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,RuntimeError,subprocess.SubprocessError) as error:
        detail=getattr(error,'stderr',None) or str(error)
        print('同步未完成：'+detail,file=sys.stderr);raise SystemExit(1)
