"""[STAGE5:ssrf-protection] SSRF-protection helpers.

Проверяет URL на безопасность для server-side fetch:
  * scheme только http/https;
  * resolved IP не попадает в private / loopback / link-local / reserved.

Известное ограничение: getaddrinfo может быть уязвим к DNS rebinding (TOCTOU).
Для B2B-сценариев достаточно; для повышенных требований — DNS pinning.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def _is_private_ip(ip) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or (ip.version == 4 and ip in ipaddress.ip_network("0.0.0.0/8"))
    )


def _resolve_ips(host: str):
    """Возвращает set[str] публичных IP или None при ошибке/приватном IP."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return None
    if not infos:
        return None
    ips = set()
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError):
            return None
        if _is_private_ip(ip):
            return None
        ips.add(str(ip))
    return ips


def is_safe_external_url(url: str, allow_private: bool = False) -> bool:
    """Возвращает True, если url безопасен для server-side fetch.

    [STAGE1.7:ssrf-dns-rebinding] TOCTOU-защита: резолвим дважды с
    задержкой 50ms. Если IP-наборы различаются — это признак DNS
    rebinding-атаки (первый resolve дал публичный IP, второй —
    приватный). Для IP-литералов проверка одноразовая (DNS не
    участвует, rebinding невозможен).
    """
    try:
        p = urlparse(str(url))
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = p.hostname
    if not host:
        return False
    if allow_private:
        return True

    try:
        ipaddress.ip_address(host)
        _is_literal = True
    except ValueError:
        _is_literal = False

    ips1 = _resolve_ips(host)
    if ips1 is None:
        return False
    if _is_literal:
        return True

    import time as _time_rb
    _time_rb.sleep(0.05)
    ips2 = _resolve_ips(host)
    if ips2 is None:
        return False
    return ips1 == ips2


def double_resolve_check(url: str, allow_private: bool = False) -> bool:
    """[STAGE1.7:ssrf-dns-rebinding] Явный API double-resolve.

    Семантически идентичен is_safe_external_url — оставлен как
    отдельное имя для явных вызовов из мест, где double-resolve
    критичен (импорт URL, webhooks, _coco_to_zip).
    """
    return is_safe_external_url(url, allow_private=allow_private)


# [PATCH:STAGE1:E1-SSRF-STREAM]
_STREAM_SCHEMES = frozenset({"rtsp", "rtsps", "rtmp", "http", "https"})


def validate_stream_url(url: str) -> tuple:
    """Validate RTSP/RTMP/HTTP stream URL. Returns (ok, reason).

    For http/https delegates to is_safe_external_url (SSRF).
    """
    if not url or not isinstance(url, str):
        return False, "empty url"
    try:
        p = urlparse(url)
    except Exception:
        return False, "unparsable url"
    scheme = (p.scheme or "").lower()
    if scheme not in _STREAM_SCHEMES:
        return False, "scheme %r not allowed" % scheme
    if not p.hostname:
        return False, "missing hostname"
    if scheme in ("http", "https"):
        if not is_safe_external_url(url):
            return False, "unsafe external url (SSRF protection)"
    return True, ""
