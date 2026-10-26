"""Exercise the real Windows bridge in staging-only mode. Retain fixtures."""
import hashlib,json,os,subprocess,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'tools')]
from package_program_installer import build
from program_updates import verify_ready

def run():
    work=ROOT/'build'/('bootstrap-check-'+str(time.time_ns()));work.mkdir(parents=True)
    version='1.0.1';media={'idle.webp':b'verified-media-fixture','素材清单.json':b'{"idle":{"file":"idle.webp"}}'}
    media_files=[dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in sorted(media.items())]
    identity=hashlib.sha256(json.dumps(media_files,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    catalog=dict(schema=1,tiers={'light':dict(id=identity,files=media_files,bytes=sum(x['bytes'] for x in media_files))})
    core={'BailongEnhanced.exe':b'MZ-only-a-stage-fixture','app/version.py':b"VERSION = '1.0.1'\n",'app/material_catalog.json':json.dumps(catalog).encode()}
    records={name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in core.items()}
    records.update({'outputs/白龙桌宠素材/'+name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in media.items()})
    descriptor=dict(schema=1,kind='program',version=version,materialId=identity,optionalMaterials=True)
    def payload(name,extra=None):
        path=work/name;data=dict(core);manifest=dict(records)
        if extra:
            data.update(extra);manifest.update({n:dict(bytes=len(v),sha256=hashlib.sha256(v).hexdigest()) for n,v in extra.items()})
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('program-update.json',json.dumps(descriptor));z.writestr('payload-manifest.json',json.dumps(dict(version=version,files=manifest)))
            for n,v in data.items():z.writestr(n,v)
        return path
    archive=payload('program.zip');result=build(archive,version,work/'valid-bootstrap',ROOT/'app/branding/bailong.ico');checks={}
    def stage(exe,label,state=None,override=None):
        state=state or work/label;state.mkdir(exist_ok=True);proof=work/(label+'.json')
        env=os.environ.copy();env['LOCALAPPDATA']=str(state)
        args=[exe,'--stage-only',str(proof)]
        if override:args+=['--payload-path',str(override)]
        done=subprocess.run(args,env=env,capture_output=True,timeout=30)
        return done.returncode,json.loads(proof.read_text(encoding='utf-8')),state
    code,data,state=stage(result['installer'],'fresh')
    assert code==0 and data['passed'];verify_ready(Path(data['source']),state/'BailongEnhanced/updates',version);checks['freshCardOnly']=True
    assert not (Path(data['source'])/'outputs').exists()
    state=work/'existing';old=state/'Programs/BailongEnhanced/versions/1.0.0-fixture/outputs/白龙桌宠素材';old.mkdir(parents=True)
    for name,value in media.items():(old/name).write_bytes(value)
    (state/'Programs/BailongEnhanced/installations.json').write_text(json.dumps(dict(current='1.0.0-fixture')))
    user=state/'BailongEnhanced/settings.json';user.parent.mkdir();user.write_text('{"preserve":true}');before=user.read_bytes()
    code,data,state=stage(result['installer'],'reuse',state)
    assert code==0 and data['passed'];verify_ready(Path(data['source']),state/'BailongEnhanced/updates',version)
    assert (Path(data['source'])/'outputs/白龙桌宠素材/idle.webp').read_bytes()==media['idle.webp'];assert user.read_bytes()==before;checks['existingMediaAndSettingsRetained']=True
    (Path(data['source'])/'BailongEnhanced.exe').write_bytes(b'changed')
    code,data,_=stage(result['installer'],'tampered-stage',state);assert code==1 and not data['passed'];checks['changedStageRejected']=True
    bad=work/'bad.zip';bad.write_bytes(b'not-the-pinned-payload')
    code,data,_=stage(result['installer'],'bad-digest',override=bad);assert code==1 and not data['passed'];checks['archiveDigestRequired']=True
    for label,entry in [('traversal','../escape.txt'),('case-collision','bailongenhanced.exe')]:
        bad=payload(label+'.zip',{entry:b'invalid'})
        item=build(bad,version,work/(label+'-bootstrap'),ROOT/'app/branding/bailong.ico')
        code,data,_=stage(item['installer'],label);assert code==1 and not data['passed'];checks[label]=True
    proof=dict(passed=all(checks.values()),checks=checks,fixtures=str(work),deploymentExecuted=False,temporaryFilesRetained=True)
    (work/'result.json').write_bytes(json.dumps(proof,indent=2).encode());print(json.dumps(proof));return proof

if __name__=='__main__':run()
