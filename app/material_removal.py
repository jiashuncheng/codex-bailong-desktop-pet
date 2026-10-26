"""Explicit user-confirmed removal of catalog-owned animations, never directories."""
import json,sys
from pathlib import Path
from material_store import checked,MaterialError
from desktop_core import atomic_json

def removal_plan(store,include_embedded=None):
    if not store.catalog:raise MaterialError('当前素材没有可验证的目录，不能自动移除')
    include_embedded=getattr(sys,'frozen',False) if include_embedded is None else include_embedded
    roots=[];catalogs=[store.catalog]
    bundled=getattr(store,'bundled_catalog',None) or store.catalog
    previous=getattr(store,'patch_previous',None)
    if previous and previous.get('catalog'):catalogs.append(previous['catalog'])
    if bundled not in catalogs:catalogs.append(bundled)
    for catalog in catalogs:
        for tier,spec in catalog['tiers'].items():
            roots.append((checked(store.cache,tier+'/'+spec['id']),spec))
    if include_embedded:roots.append((store.base,bundled['tiers']['light']))
    plan=[];seen=set()
    for root,spec in roots:
        for entry in spec['files']:
            # Keep the tiny manifest as metadata; only actual animation bytes.
            if Path(entry['path']).suffix.lower() not in ('.webp','.webm','.png'):continue
            p=checked(root,entry['path'])
            key=(str(root),entry['path'])
            if key in seen:continue
            seen.add(key)
            if p.is_file():
                s=p.stat();plan.append(dict(root=str(root),name=entry['path'],bytes=s.st_size,mtime=s.st_mtime_ns))
    return plan

def remove_animations(store,plan,unlink=None):
    # The caller must obtain explicit confirmation and stop the decoder first.
    valid={(i['root'],i['name']):i for i in removal_plan(store,include_embedded=True)}
    for item in plan:
        if valid.get((item['root'],item['name']))!=item:raise MaterialError('素材文件已经改变，请重新确认移除')
    atomic_json(store.preference,dict(schema=1,tier=store.preferred,cardOnly=True))
    store.card_only=True;store.current=None;removed=0
    try:
        for item in plan:
            path=checked(Path(item['root']),item['name'])
            (unlink or Path.unlink)(path);removed+=1
    finally:
        for tier in ('light','hd'):store.available(tier)
        # A managed installation's integrity list must reflect removed media.
        manifest=store.app_root/'payload-manifest.json'
        if manifest.is_file():
            data=json.loads(manifest.read_text(encoding='utf-8'));files=data.get('files',{})
            for item in plan:
                p=checked(Path(item['root']),item['name'])
                if p.is_relative_to(store.app_root) and not p.exists():files.pop(p.relative_to(store.app_root).as_posix(),None)
            atomic_json(manifest,data)
    return removed
