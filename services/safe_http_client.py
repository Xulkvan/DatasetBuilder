"""[STAGE9_DNS_PINNING] DNS-pinned HTTP client for SSRF defense-in-depth.

Защита от DNS rebinding: is_safe_external_url делает double-resolve
(2 × getaddrinfo с паузой 50 мс), но между проверкой и фактическим
connect у httpx/urllib остаётся TOCTOU-окно — атакующий может
вернуть публичный IP на проверке и приватный на connect.

_PinnedTransport резолвит host один раз, проверяет каждый IP через
_is_private_ip, подключается к первому публичному IP напрямую и
передаёт оригинальный hostname в заголовке Host.

Ограничение: TLS SNI ломается при подключении к bare IP — https://
URLs используют fallback на is_safe_external_url (см. ADR-0013).
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional

import httpx


class _PinnedTransport(httpx.HTTPTransport):
    """HTTP transport that pins http:// connections to a pre-checked IP.

    * http://  — full pinning: resolve once, verify, connect to pin_ip,
                 original hostname передаётся в заголовке Host.
    * https:// — fallback: is_safe_external_url + super() (TLS SNI-ограничение).
    """

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        scheme = request.url.scheme
        host = request.url.host

        if scheme == "https":
            # Fallback: double-resolve (TLS SNI нельзя сохранить на bare IP).
            from services.url_safety import is_safe_external_url
            if not is_safe_external_url(str(request.url)):
                raise httpx.ConnectError(
                    f"Unsafe URL blocked (SSRF protection): {host}"
                )
            return super().handle_request(request)

        if scheme != "http":
            raise httpx.ConnectError(f"Unsupported scheme: {scheme!r}")

        # --- http: pin to first public IP ---
        port = request.url.port or 80
        try:
            infos = socket.getaddrinfo(host, port)
        except socket.gaierror as _e:
            raise httpx.ConnectError(f"Cannot resolve {host}: {_e}")

        from services.url_safety import _is_private_ip
        pin_ip: Optional[str] = None
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError):
                continue
            if _is_private_ip(ip):
                raise httpx.ConnectError(
                    f"Private IP {ip} blocked (SSRF protection)"
                )
            if pin_ip is None:
                pin_ip = str(ip)

        if pin_ip is None:
            raise httpx.ConnectError(f"Cannot resolve {host}")

        # Пересобираем URL с pin_ip; оригинальный hostname — в Host.
        try:
            new_url = request.url.copy_with(host=pin_ip)
        except Exception as _e:
            raise httpx.ConnectError(
                f"Cannot build pinned URL for {host}: {_e}"
            )

        new_headers = dict(request.headers)
        for _k in [k for k in new_headers if k.lower() == "host"]:
            del new_headers[_k]
        _host_value = host
        if request.url.port:
            _host_value = f"{host}:{request.url.port}"
        new_headers["host"] = _host_value

        new_request = httpx.Request(
            method=request.method,
            url=new_url,
            headers=new_headers,
            # Use bytes instead of stream: passing a raw stream to
            # httpx.Request(content=...) forces Transfer-Encoding:
            # chunked even for empty GET bodies. Some servers (e.g.
            # BaseHTTPRequestHandler in tests) do not consume the
            # chunked terminator, leaving unread bytes in the socket;
            # Windows then sends RST (WinError 10053) instead of a
            # clean FIN, surfacing as httpx.ReadError on the client.
            content=request.content,
            extensions=request.extensions,
        )
        return super().handle_request(new_request)


def get_safe_client(timeout: float = 30.0) -> httpx.Client:
    """Return httpx.Client with DNS pinning for http:// URLs."""
    return httpx.Client(
        transport=_PinnedTransport(),
        timeout=timeout,
        follow_redirects=True,
    )
