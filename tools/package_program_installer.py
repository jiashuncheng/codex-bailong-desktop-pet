"""Package a media-free program bootstrap, including the old updater ZIP alias."""
import hashlib,json,os,re,subprocess,zipfile
from pathlib import Path

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def compiler_paths():
    windows=Path(os.environ.get('WINDIR',r'C:\Windows'))
    framework=windows/'Microsoft.NET/Framework64/v4.0.30319';compiler=framework/'csc.exe'
    if not compiler.is_file():raise FileNotFoundError('Windows .NET Framework C# compiler not found')
    libraries=[]
    for name in ('System.IO.Compression','System.IO.Compression.FileSystem','System.Web.Extensions','System.Windows.Forms'):
        direct=framework/(name+'.dll')
        candidates=[direct] if direct.is_file() else sorted((windows/'Microsoft.NET/assembly/GAC_MSIL'/name).glob('*/'+name+'.dll'))
        if not candidates:raise FileNotFoundError('Missing .NET runtime library: '+name)
        libraries.append(candidates[-1])
    return compiler,libraries

def build(program,version,destination,icon):
    program=Path(program).resolve();destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version):raise ValueError('Invalid public version')
    with zipfile.ZipFile(program) as archive:
        descriptor=json.loads(archive.read('program-update.json'))
        manifest=json.loads(archive.read('payload-manifest.json'))
        if descriptor.get('version')!=version or manifest.get('version')!=version or descriptor.get('optionalMaterials') is not True:raise ValueError('Not a compatible program-only payload')
    sha=digest(program);work=destination/'bootstrap-build'
    if work.exists():raise FileExistsError(work)
    work.mkdir()
    template=Path(__file__).with_name('ProgramPatchBootstrap.cs').read_text(encoding='utf-8')
    source=work/'ProgramPatchBootstrap.cs';source.write_bytes(template.replace('@@VERSION@@',version).replace('@@PAYLOAD_SHA@@',sha).encode('utf-8'))
    compiler,libraries=compiler_paths();exe=destination/f'白龙桌宠-{version}-一键部署.exe'
    command=[str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',f'/out:{exe}',f'/win32icon:{Path(icon).resolve()}',f'/resource:{program},Bailong.Program',*[f'/reference:{p}' for p in libraries],str(source)]
    subprocess.run(command,cwd=work,check=True,capture_output=True)
    return dict(version=version,installer=str(exe),installerBytes=exe.stat().st_size,programSha256=sha,installerSha256=digest(exe))

def package(program,version,destination,icon):
    result=build(program,version,destination,icon);destination=Path(destination)
    notes='程序补丁安装器 '+version+'\n\n已有用户：复用可校验的本机动画，保留设置、统计和回退版本。\n新用户：先安装卡片程序，在设置的素材页按需下载轻量或高清动画。\n该安装器不包含动画资源。程序 ZIP / JSON 供软件内更新使用。\n'
    name=f'bailong-desktop-pet-{version}-windows-x64.zip';archive=destination/name
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        z.write(result['installer'],Path(result['installer']).name)
        z.writestr('程序补丁说明.txt',notes)
    sums=destination/'SHA256SUMS.txt';records={}
    if sums.is_file():
        for line in sums.read_text(encoding='utf-8-sig').splitlines():
            fields=line.split(maxsplit=1)
            if len(fields)==2:records[fields[1].lstrip('*')]=fields[0]
    records[name]=digest(archive);sums.write_bytes(''.join(sha+'  '+name+'\n' for name,sha in sorted(records.items())).encode('utf-8'))
    return dict(result,archive=str(archive),archiveBytes=archive.stat().st_size,archiveSha256=records[name],includesAnimations=False)
