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


def is_safe_external_url(url: str, allow_private: bool = False) -> bool:
    """Возвращает True, если url безопасен для server-side fetch."""
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
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError):
            return False
        if _is_private_ip(ip):
            return False
    return True
