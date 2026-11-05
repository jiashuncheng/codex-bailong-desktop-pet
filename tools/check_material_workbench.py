"""Run material workbench regressions in isolated processes and user directories."""
from pathlib import Path
import json,os,re,subprocess,sys,tempfile

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/'tools/material_workbench'

def main():
    results=[]
    for path in sorted(TOOL.glob('test_*.py')):
        with tempfile.TemporaryDirectory(prefix='bailong-workbench-check-') as temp:
            home=Path(temp)
            env=dict(os.environ,LOCALAPPDATA=temp,BAILONG_DATA_DIR=str(home/'data'),CODEX_HOME=str(home/'codex'),
                BAILONG_ISOLATED='1',QT_QPA_PLATFORM='offscreen',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',
                PYTHONPATH=os.pathsep.join(map(str,(TOOL,ROOT/'app',ROOT))))
            try:
                process=subprocess.run([sys.executable,'-m','unittest',path.stem],cwd=TOOL,env=env,
                    capture_output=True,text=True,encoding='utf-8',timeout=120)
                found=re.findall(r'Ran (\d+) tests?',process.stderr)
                count=int(found[-1]) if found else 0
                result=dict(module=path.stem,tests=count,passed=process.returncode==0 and count>0)
                if not result['passed']:result['error']=(process.stdout+process.stderr)[-8000:]
            except subprocess.TimeoutExpired:
                result=dict(module=path.stem,tests=0,passed=False,error='120 second timeout')
            results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
    report=dict(passed=bool(results) and all(r['passed'] for r in results),tests=sum(r['tests'] for r in results),modules=results)
    directory=ROOT/'.checks';directory.mkdir(exist_ok=True)
    (directory/'material-workbench.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"Workbench: {report['tests']} tests; passed={report['passed']}")
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
