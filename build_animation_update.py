"""Explicitly package animation releases in the shared public version sequence."""
import argparse,copy,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'app'))
from animation_updates import validate_catalog
from app_updates import version_tuple
from material_store import checked,hash_file

def verify_combined(destination,catalog,version):
    program=Path(destination)/f'bailong-desktop-pet-{version}-program.zip'
    if program.exists():
        with zipfile.ZipFile(program) as archive:actual=json.loads(archive.read('app/material_catalog.json'))
        if actual!=catalog:raise ValueError('同批程序包与动画补丁目录不一致，须按本次动画目录重新构建程序包')

def package(catalog_path,light_source,hd_source,destination,version,minimum):
    version_tuple(version);version_tuple(minimum)
    if version_tuple(minimum)>version_tuple(version):raise ValueError('最低程序版本不能高于补丁版本')
    catalog=copy.deepcopy(json.loads(Path(catalog_path).read_text(encoding='utf-8-sig')))
    catalog['releaseVersion']=version;destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    outputs=[]
    for tier,source in [('light',light_source),('hd',hd_source)]:
        source=Path(source);spec=catalog['tiers'][tier]
        name=f'bailong-desktop-pet-{version}-animation-{tier}.zip';path=destination/name
        if path.exists():raise FileExistsError(path)
        with zipfile.ZipFile(path,'w',zipfile.ZIP_STORED) as archive:
            for record in spec['files']:
                file=checked(source,record['path'])
                if file.stat().st_size!=record['bytes'] or hash_file(file)!=record['sha256']:raise ValueError('动画源文件校验失败：'+record['path'])
                archive.write(file,record['path'])
        spec.update(url=f'https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/v{version}/{name}',archiveBytes=path.stat().st_size,archiveSha256=hash_file(path))
        outputs.append(path)
    validate_catalog(catalog,version);verify_combined(destination,catalog,version)
    data=dict(schema=1,kind='animation',version=version,minimumProgramVersion=minimum,catalog=catalog)
    descriptor=destination/f'bailong-desktop-pet-{version}-animation.json'
    descriptor.write_bytes(json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'));outputs.append(descriptor)
    (destination/f'animation-catalog-{version}.json').write_bytes(json.dumps(catalog,ensure_ascii=False,indent=2).encode('utf-8'))
    sums=destination/'SHA256SUMS.txt';records={}
    if sums.exists():
        for line in sums.read_text(encoding='utf-8-sig').splitlines():
            parts=line.split(maxsplit=1)
            if len(parts)==2:records[parts[1].lstrip('*')]=parts[0]
    records.update({path.name:hash_file(path) for path in outputs})
    sums.write_bytes(''.join(sha+'  '+name+'\n' for name,sha in sorted(records.items())).encode('utf-8'))
    return data

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('catalog','light-source','hd-source','destination','version','minimum-program-version'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();package(args.catalog,args.light_source,args.hd_source,args.destination,args.version,args.minimum_program_version)
