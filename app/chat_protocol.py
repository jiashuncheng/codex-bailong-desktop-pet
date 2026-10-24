"""Shared validation and bounded, credential-redacted chat error presentation."""
import ipaddress
import re
from urllib.parse import quote, unquote, urlsplit


class ProviderValidationError(ValueError):
    def __init__(self, message, field):
        super().__init__(message)
        self.field = field


def endpoint_for(provider):
    raw = provider.get('base_url', '') if isinstance(provider, dict) else ''
    if not isinstance(raw, str) or not raw.strip():
        raise ProviderValidationError('请填写服务的 API 地址。', 'base_url')
    url = raw.strip().rstrip('/')
    try:
        parts = urlsplit(url)
        port = parts.port
        valid = (parts.scheme in ('http', 'https') and parts.hostname and
                 not parts.username and not parts.password and not parts.query and
                 not parts.fragment and not re.search(r'\s|[\x00-\x1f\x7f]', url) and
                 '\\' not in url and port != 0)
    except ValueError:
        valid = False
    if not valid:
        raise ProviderValidationError('服务地址需为完整的 http/https API 地址，不能包含账号、查询参数或片段。', 'base_url')
    host = parts.hostname.lower()
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == 'localhost'
    if parts.scheme == 'http' and not local:
        raise ProviderValidationError('远程服务请使用 HTTPS；本地服务可以使用 HTTP。', 'base_url')
    path = unquote(parts.path).rstrip('/').lower()
    if path.endswith(('/responses', '/messages', '/models', '/completions')) and not path.endswith('/chat/completions'):
        raise ProviderValidationError('当前支持 Chat Completions；请填写该协议的基础地址或完整 /chat/completions 地址。', 'base_url')
    return url if path.endswith('/chat/completions') else url + '/chat/completions'


def normalize_provider(provider):
    endpoint_for(provider)
    model = provider.get('model', '')
    if not isinstance(model, str) or not model.strip() or re.search(r'[\x00-\x1f\x7f]', model):
        raise ProviderValidationError('请填写服务提供的准确模型名称。', 'model')
    timeout = provider.get('timeout', 90)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 5 <= timeout <= 600:
        raise ProviderValidationError('超时需为 5—600 秒。', 'timeout')
    return dict(provider, base_url=provider['base_url'].strip().rstrip('/'), model=model.strip(), timeout=int(timeout))


def safe_detail(value, key=''):
    if not isinstance(value, str):
        return ''
    # Redact before truncation so a clipped credential cannot escape the match.
    for secret in (key, quote(key, safe='') if key else ''):
        if secret:
            value = value.replace(secret, '[密钥已隐藏]')
    value = re.sub(r'(?i)\bBearer\s+[^\s,;"<>]+', 'Bearer [密钥已隐藏]', value)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[密钥已隐藏]', value)
    if '<html' in value.lower() or '<!doctype' in value.lower():
        return ''
    value = re.sub(r'<[^>]*>', '', value)
    value = re.sub(r'[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]', ' ', value)
    return ' '.join(value.split())[:240]


def service_error(status, document=None, key=''):
    error = document.get('error') if isinstance(document, dict) else None
    if isinstance(error, dict):
        message = error.get('message', '')
        code = error.get('code') or error.get('type') or ''
    elif isinstance(error, str):
        message, code = error, ''
    else:
        message, code = '', ''
    clue = (str(code) + ' ' + str(message)).lower()
    prefix = f'模型服务 HTTP {status}：' if status and status >= 300 else '模型服务：'
    if status and 300 <= status < 400:
        summary = '地址发生重定向，请使用服务提供的最终 API 地址'
    elif any(s in clue for s in ('insufficient_quota', 'insufficient balance', 'credit balance', '余额不足')):
        summary = 'API 余额或额度不足，请检查服务账户'
    elif status == 401 or any(s in clue for s in ('invalid_api_key', 'incorrect api key', 'invalid api key')):
        summary = '密钥无效或已过期，请重新检查 API 密钥'
    elif status == 403:
        summary = '服务拒绝访问，请检查模型权限或访问限制'
    elif status == 429:
        summary = '请求受到限制，请检查服务额度或稍后重试'
    elif 'model_not_found' in clue or 'model not found' in clue:
        summary = '模型不存在或无权使用，请检查模型名称'
    elif status == 404:
        summary = '接口地址或模型不存在，请检查最终请求地址和模型名'
    elif any(s in clue for s in ('unsupported', 'not support', '不支持')):
        summary = '服务不支持当前模型、参数或流式协议'
    elif status and status >= 500:
        summary = '服务端暂时异常，请稍后重试'
    else:
        summary = '请求未成功，请检查服务配置'
    detail = safe_detail(message, key)
    return prefix + summary + ('；服务说明：' + detail if detail else '')
