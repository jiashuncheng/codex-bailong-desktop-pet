"""Immutable, content-addressed built-in materials, independent of app versions."""
import hashlib,json,os,shutil,stat,tempfile,uuid,zipfile
from pathlib import Path,PurePosixPath
from urllib.error import HTTPError,URLError
from desktop_core import atomic_json
from app_updates import open_url,UpdateCancelled

class MaterialError(ValueError):pass

def checked(root,name):
    if not isinstance(name,str) or '\\' in name or ':' in name:raise MaterialError('素材路径无效')
    p=PurePosixPath(name)
    if p.is_absolute() or any(v in ('','.','..') for v in name.split('/')):raise MaterialError('素材路径无效')
    root=Path(root);target=root.joinpath(*p.parts)
    if root.is_symlink() or any(v.is_symlink() or getattr(v,'is_junction',lambda:False)() for v in [target,*target.parents] if v!=root.parent and (v==root or root in v.parents)):raise MaterialError('素材目录不能使用链接跳转')
    # Windows may report another name of a multiply hard-linked file. All
    # reparse points above are rejected; validate its directory, not that alias.
    if not target.parent.resolve().is_relative_to(root.resolve()):raise MaterialError('素材路径越界')
    return target

def cancelled(cancel):
    if cancel():raise UpdateCancelled('素材操作已取消，继续使用原画质')

def hash_file(path,cancel=lambda:False):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data:=stream.read(1024*1024):cancelled(cancel);h.update(data)
    return h.hexdigest()

class MaterialStore:
    def __init__(self,app_root,state_dir,catalog_override=None):
        self._known_availability={}
        self.app_root=Path(app_root);self.state=Path(state_dir);self.base=self.app_root/'outputs/白龙桌宠素材'
        from storage_locations import material_root
        self.location_error=''
        try:self.cache=material_root(self.state) if (self.state/'material-location.json').exists() or not (self.app_root/'portable-materials.json').is_file() else self.app_root/'materials'
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.cache=self.state/'materials';self.location_error='动画目录配置不可读，请重新选择存储位置'
        self.preference=self.state/'material-preferences.json'
        catalog_path=self.app_root/'app/material_catalog.json'
        self.catalog=json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.is_file() else None
        self.bundled_catalog=self.catalog;self.patch_previous=None
        self.embedded_light_id=self.catalog['tiers']['light']['id'] if self.catalog else None
        if catalog_override is None:
            from animation_updates import load_override
            from version import VERSION
            overlay=load_override(VERSION,self.state,self.bundled_catalog)
            if overlay:self.catalog=overlay['catalog'];self.patch_previous=overlay.get('previous')
        else:self.catalog=catalog_override
        if self.catalog:
            if self.catalog.get('schema')!=1:raise MaterialError('素材目录版本不受支持')
            for tier in self.catalog['tiers'].values():
                if not tier['id'].isalnum() or len(tier['files'])>128:raise MaterialError('素材目录无效')
                for f in tier['files']:
                    checked(self.base,f['path'])
                    if not 0<f['bytes']<2**31 or len(f['sha256'])!=64:raise MaterialError('素材校验信息无效')
        try:
            prefs=json.loads(self.preference.read_text(encoding='utf-8'))
            if not isinstance(prefs,dict):raise ValueError('画质偏好应为对象')
            self.preferred=prefs['tier']
        except (OSError,ValueError,KeyError):prefs={};self.preferred='light'
        self.card_only=bool(prefs.get('cardOnly',False))
        if self.preferred not in ('light','hd','local_hd'):self.preferred='light'
        self.current='light' if self.catalog else 'hd';self.root=self.base
        # Development assets are originals; frozen base is always the light tier.
        self.development=not getattr(__import__('sys'),'frozen',False) and (self.app_root/'build/materials/light/素材清单.json').is_file()
        if self.development:self.root=self.app_root/'build/materials/light'
        # Establish display-only availability before the animated UI starts.
        # Runtime/settings snapshots must never rescan all material paths.
        light_ready=self.available('light');hd_ready=self.available('hd');local_ready=self.available('local_hd')
        if self.catalog:
            selected=self.preferred if self.known_available(self.preferred) else 'light' if light_ready else 'hd' if hd_ready else 'local_hd' if local_ready else None
            self.current=selected if not self.card_only else None
            if self.current:self.root=self.tier_root(self.current)

    def local_hd_info(self):
        try:
            info=json.loads((self.cache/'local-hd.json').read_text(encoding='utf-8'))
            if info['id']!=self.catalog['tiers']['hd']['id']:return {}
            checked(self.cache,info['root'])
            return info
        except (OSError,ValueError,KeyError,TypeError):return {}

    def tier_root(self,tier):
        if tier=='local_hd':
            info=self.local_hd_info()
            if not info:raise MaterialError('尚未导入本地高清素材')
            return checked(self.cache,info['root'])

        if tier not in ('light','hd','local_hd'):raise MaterialError('未知素材画质')
        if tier=='light':
            embedded=self.app_root/'build/materials/light' if self.development else self.base
            spec=self.catalog['tiers']['light'] if self.catalog else None
            if spec and spec['id']==self.embedded_light_id and all(checked(embedded,f['path']).is_file() for f in spec['files']):return embedded
        return checked(self.cache,tier+'/'+self.catalog['tiers'][tier]['id'])

    def available(self,tier):
        result=self._check_available(tier)
        self._known_availability[tier]=result
        return result

    def known_available(self,tier):
        """Last checked display hint only; never authorizes activation or reuse."""
        return self._known_availability.get(tier,False)

    def _check_available(self,tier):
        if not self.catalog:return tier=='hd'
        if tier=='local_hd':
            try:
                info=self.local_hd_info();root=self.tier_root(tier)
                expected={f['path'] for f in self.catalog['tiers']['light']['files']}
                if set(info['files'])!=expected:return False
                for name,record in info['files'].items():
                    s=checked(root,name).stat()
                    if record['stat']!=[s.st_size,s.st_mtime_ns]:return False
                return True
            except (OSError,ValueError,KeyError,TypeError):return False
        root=self.tier_root(tier)
        if tier=='light' and root in (self.base,self.app_root/'build/materials/light'):return (root/'素材清单.json').is_file()
        try:
            receipt=json.loads((root/'.verified.json').read_text(encoding='utf-8'))
            if receipt['id']!=self.catalog['tiers'][tier]['id']:return False
            for f in self.catalog['tiers'][tier]['files']:
                p=checked(root,f['path']);s=p.stat()
                if receipt['files'][f['path']]!=[s.st_size,s.st_mtime_ns] or s.st_size!=f['bytes']:return False
            return True
        except (OSError,ValueError,KeyError):return False

    def verify(self,root,tier,cancel=lambda:False,progress=lambda n,t,p:None):
        if tier=='local_hd':
            info=self.local_hd_info()
            files=[f for t in ('light','hd') for f in self.catalog['tiers'][t]['files'] if info.get('files',{}).get(f['path'],{}).get('tier')==t]
            if len(files)!=len(self.catalog['tiers']['light']['files']):raise MaterialError('本地素材清单不完整')
        else:files=self.catalog['tiers'][tier]['files']
        total=sum(f['bytes'] for f in files);done=0
        for f in files:
            cancelled(cancel);p=checked(root,f['path'])
            if p.stat().st_size!=f['bytes'] or hash_file(p,cancel)!=f['sha256']:raise MaterialError('素材校验失败：'+f['path'])
            done+=f['bytes'];progress(done,total,'verifying')
        return True

    def import_local_hd(self,source,cancel=lambda:False,progress=lambda n,t,p:None):
        """Build an immutable snapshot: verified HD where present, light otherwise."""
        source=Path(source).expanduser().resolve()
        if not source.is_dir():raise MaterialError('本地高清目录不存在')
        light={f['path']:f for f in self.catalog['tiers']['light']['files']}
        selected=[]
        for hd in self.catalog['tiers']['hd']['files']:
            cancelled(cancel);src=checked(source,hd['path'])
            tier='hd' if src.is_file() else 'light'
            spec=hd if tier=='hd' else light[hd['path']]
            if tier=='light':src=checked(self.tier_root('light'),hd['path'])
            if src.stat().st_size!=spec['bytes'] or hash_file(src,cancel)!=spec['sha256']:
                raise MaterialError('素材校验失败：'+hd['path'])
            selected.append((tier,spec,src))
        if not any(t=='hd' and f['path'].endswith('.webp') for t,f,p in selected):
            raise MaterialError('目录内尚无可用的高清动画')
        identity=hashlib.sha256(json.dumps([(t,f['path'],f['sha256']) for t,f,p in selected]).encode()).hexdigest()[:24]
        relative='local-hd/'+self.catalog['tiers']['hd']['id']+'/'+identity
        target=checked(self.cache,relative);self.cache.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='local-import-',dir=self.cache) as temp:
            stage=Path(temp)/'snapshot';stage.mkdir();records={};done=0;total=sum(f['bytes'] for t,f,p in selected)
            for tier,spec,src in selected:
                cancelled(cancel);dst=checked(stage,spec['path']);dst.parent.mkdir(parents=True,exist_ok=True)
                # Keep the active snapshot independent from the syncing source.
                shutil.copy2(src,dst)
                if dst.stat().st_size!=spec['bytes'] or hash_file(dst,cancel)!=spec['sha256']:
                    raise MaterialError('复制后素材校验失败：'+spec['path'])
                s=dst.stat();records[spec['path']]=dict(tier=tier,stat=[s.st_size,s.st_mtime_ns])
                done+=spec['bytes'];progress(done,total,'verifying')
            cancelled(cancel)
            # Reuse an unchanged snapshot only after checking its actual contents.
            if target.exists():
                for tier,spec,src in selected:
                    dst=checked(target,spec['path'])
                    if dst.stat().st_size!=spec['bytes'] or hash_file(dst,cancel)!=spec['sha256']:
                        raise MaterialError('已有本地素材缓存损坏，请保留当前画质并联系维护')
                    s=dst.stat();records[spec['path']]['stat']=[s.st_size,s.st_mtime_ns]
            else:
                target.parent.mkdir(parents=True,exist_ok=True);stage.replace(target)
            info=dict(schema=1,id=self.catalog['tiers']['hd']['id'],root=relative,source=str(source),files=records,
                      hd_files=[f['path'] for t,f,p in selected if t=='hd'],fallback_files=[f['path'] for t,f,p in selected if t=='light'])
            atomic_json(self.cache/'local-hd.json',info)
        return target

    def _receipt(self,root,tier):
        files={}
        for f in self.catalog['tiers'][tier]['files']:
            s=checked(root,f['path']).stat();files[f['path']]=[s.st_size,s.st_mtime_ns]
        atomic_json(root/'.verified.json',dict(id=self.catalog['tiers'][tier]['id'],files=files))

    def import_hd(self,source,cancel=lambda:False,progress=lambda n,t,p:None):
        """Seed from an existing verified 720px install without changing its files."""
        target=self.tier_root('hd');self.cache.mkdir(parents=True,exist_ok=True)
        self.verify(source,'hd',cancel,progress)
        if self.available('hd'):return target
        stage=self.cache/('staging-'+uuid.uuid4().hex);stage.mkdir()
        try:
            for f in self.catalog['tiers']['hd']['files']:
                cancelled(cancel);src=checked(source,f['path']);dst=checked(stage,f['path']);dst.parent.mkdir(parents=True,exist_ok=True)
                try:os.link(src,dst)
                except OSError:shutil.copy2(src,dst)
            self.verify(stage,'hd',cancel,progress);self._receipt(stage,'hd');self._commit(stage,target)
            return target
        finally:
            if stage.exists():shutil.rmtree(stage)

    def _commit(self,stage,target,tier='hd'):
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            # Never change an existing cache directory while a player may read it.
            if self.available(tier):return
            if not self.card_only:raise MaterialError('已有素材缓存损坏，请移除动画资源后重试')
            if not target.resolve().is_relative_to(self.cache.resolve()):raise MaterialError('素材缓存位置无效')
            # Explicit removal may retain metadata or a file locked by another
            # process. Keep that remainder; publish a fresh verified directory.
            target.replace(self.cache/('retained-'+uuid.uuid4().hex))
        stage.replace(target)
        self._known_availability[tier]=True

    def ensure(self,tier,cancel=lambda:False,progress=lambda n,t,p:None,opener=None):
        if self.location_error:raise MaterialError(self.location_error)
        if not self.catalog:raise MaterialError('当前版本没有可切换的素材目录')
        root=self.tier_root(tier)
        if self.available(tier):self.verify(root,tier,cancel,progress);return root
        if tier=='local_hd':raise MaterialError('本地高清缓存不可用，请运行更新本地高清素材脚本')
        spec=self.catalog['tiers'][tier]
        version=self.catalog.get('releaseVersion')
        expected=(f'https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/v{version}/bailong-desktop-pet-{version}-animation-{tier}.zip' if version else f"https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/materials-{spec['id']}/bailong-{tier}-{spec['id']}.zip")
        url=spec.get('url',expected)
        if url!=expected:raise MaterialError('高清素材下载地址无效')
        self.cache.mkdir(parents=True,exist_ok=True)
        # A single fresh transaction; incomplete downloads are discarded on cancel.
        with tempfile.TemporaryDirectory(prefix='download-',dir=self.cache) as work:
            work=Path(work);archive=work/'materials.zip';stage=work/'extracted';stage.mkdir()
            maximum=spec['bytes']+len(spec['files'])*4096+1024*1024
            try:
                response=(opener or open_url)(url,{'Accept':'application/octet-stream'})
                with response,archive.open('wb') as output:
                    total=int(response.headers.get('Content-Length','0'));done=0
                    if total<0 or total>maximum:raise MaterialError('素材下载大小异常')
                    while data:=response.read(256*1024):
                        cancelled(cancel);done+=len(data)
                        if done>maximum:raise MaterialError('素材下载超出上限')
                        output.write(data);progress(done,total,'downloading')
                    if total and done!=total:raise MaterialError('素材下载不完整，请重试')
            except HTTPError as exc:
                if exc.code==404:raise MaterialError('这套素材尚未公开发布；本机已有素材和卡片功能仍可使用') from exc
                raise MaterialError('素材服务暂时不可用，请稍后重试') from exc
            except (URLError,TimeoutError,OSError) as exc:raise MaterialError('素材下载连接失败，请稍后重试') from exc
            cancelled(cancel)
            if spec.get('archiveSha256') and (archive.stat().st_size!=spec.get('archiveBytes') or hash_file(archive,cancel)!=spec['archiveSha256']):raise MaterialError('动画补丁压缩包校验失败')
            try:
                with zipfile.ZipFile(archive) as z:
                    expected_files={f['path']:f for f in spec['files']};infos=z.infolist()
                    if len(infos)!=len(expected_files) or len({i.filename for i in infos})!=len(infos):raise MaterialError('素材压缩包文件数量异常')
                    for i in infos:
                        cancelled(cancel);target=checked(stage,i.filename)
                        if i.filename not in expected_files or i.file_size!=expected_files[i.filename]['bytes'] or stat.S_ISLNK(i.external_attr>>16) or i.is_dir():raise MaterialError('素材压缩包内容异常')
                        target.parent.mkdir(parents=True,exist_ok=True)
                        with z.open(i) as src,target.open('wb') as dst:
                            count=0
                            while data:=src.read(256*1024):
                                cancelled(cancel);count+=len(data)
                                if count>i.file_size:raise MaterialError('解压大小异常')
                                dst.write(data)
                self.verify(stage,tier,cancel,progress);self._receipt(stage,tier);cancelled(cancel);self._commit(stage,root,tier)
            except (zipfile.BadZipFile,RuntimeError) as exc:raise MaterialError('素材压缩包无效') from exc
        return root

    def activate(self,tier,root):
        if Path(root)!=self.tier_root(tier) or not self.available(tier):raise MaterialError('素材尚未准备完成')
        atomic_json(self.preference,dict(schema=1,tier=tier,cardOnly=False))
        self.preferred=tier;self.current=tier;self.root=Path(root);self.card_only=False
