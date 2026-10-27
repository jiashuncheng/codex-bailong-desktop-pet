"""Small display labels from session provenance; never infer a host from a title."""
import re

def metadata_source(metadata):
    if metadata.get('originator')=='BailongSSHBridge' and metadata.get('source')=='bailong_ssh_bridge':
        host=metadata.get('remote_host')
        if isinstance(host,str) and re.fullmatch(r'[\w.-]{1,64}',host):return 'ssh',host
        return 'ssh','SSH'
    if metadata.get('originator')=='BailongSSHBridge':return 'ssh','SSH'
    origin=str(metadata.get('originator','')).casefold()
    if origin in ('codex desktop','codex_work_desktop'):return 'local','本机'
    if metadata.get('source')=='cli' or origin in ('codex-tui','codex-cli'):return 'terminal','终端'
    return 'local','本机'

def session_source(session,wsl=False):
    kind=getattr(session,'source_kind','');label=getattr(session,'source_label','')
    if kind=='ssh':return dict(source_kind=kind,source_label=label or 'SSH')
    if wsl:return dict(source_kind='wsl',source_label='WSL')
    return dict(source_kind=kind or 'local',source_label=label or '本机')
