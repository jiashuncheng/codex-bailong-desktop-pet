"""Capsule shortcuts: local actions or a browser URL, never shell commands."""
from urllib.parse import urlsplit

ACTIONS=(('chatgpt','GPT 网页','web'),('codex','打开 Codex','code'),
         ('chat','白龙闲聊','chat'),('report','数据面板','report'),
         ('refresh','刷新全部数据','refresh'),('settings','设置','settings'),
         ('website','自定义网页','web'))
DEFAULT_ACTION='chatgpt'

def action_info(value):
    return next((item for item in ACTIONS if item[0]==value),ACTIONS[0])

def website_url(value):
    value=str(value or '').strip()
    if not value or len(value)>2048 or any(ord(c)<32 for c in value):
        raise ValueError('请输入完整的 http:// 或 https:// 网页地址。')
    try:
        parts=urlsplit(value)
        if parts.scheme.lower() not in ('http','https') or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        parts.port
    except ValueError:
        raise ValueError('只支持 http:// 或 https:// 网页地址，不支持命令、文件路径或带密码的地址。') from None
    return value
