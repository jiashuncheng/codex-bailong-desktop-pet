"""Explicit, pinned model download; never fetch models while importing the UI."""
from pathlib import Path
import hashlib,json,os,tempfile,urllib.request

BASE=Path(__file__).resolve().parent

def matches(path,entry):
    path=Path(path)
    return path.is_file() and path.stat().st_size==entry['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256']

def download(entry,target,opener=urllib.request.urlopen):
    target=Path(target)
    if matches(target,entry):return False
    if not entry['url'].startswith('https://'):raise ValueError('Model URL must use HTTPS')
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='model-',suffix='.tmp',dir=target.parent)
    temporary=Path(name)
    try:
        with os.fdopen(fd,'wb') as out,opener(entry['url'],timeout=30) as response:
            size=0
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>entry['bytes']:raise ValueError('Model is larger than the pinned size')
                out.write(chunk)
        if not matches(temporary,entry):raise ValueError('Model size / SHA-256 mismatch; existing file was preserved')
        os.replace(temporary,target)
        return True
    finally:
        temporary.unlink(missing_ok=True)

def main():
    entries=json.loads((BASE/'models.json').read_text(encoding='utf-8'))
    for name,entry in entries.items():
        updated=download(entry,BASE/'models'/name)
        print(('Downloaded and verified: ' if updated else 'Already verified: ')+name)
    return 0

if __name__=='__main__':raise SystemExit(main())
