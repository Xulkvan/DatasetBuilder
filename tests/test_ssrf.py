"""[STAGE6:test-ssrf] SSRF-protection unit tests."""
import socket

from services.url_safety import is_safe_external_url


def test_localhost_blocked():
    assert not is_safe_external_url("http://127.0.0.1:8000/")
    assert not is_safe_external_url("http://localhost:8000/")
    assert not is_safe_external_url("http://[::1]:8000/")


def test_metadata_ip_blocked():
    assert not is_safe_external_url("http://169.254.169.254/")


def test_private_network_blocked():
    assert not is_safe_external_url("http://192.168.1.1/")
    assert not is_safe_external_url("http://10.0.0.1/")
    assert not is_safe_external_url("http://172.16.0.1/")


def test_non_http_schemes_blocked():
    assert not is_safe_external_url("file:///etc/passwd")
    assert not is_safe_external_url("ftp://example.com/")
    assert not is_safe_external_url("javascript:alert(1)")


def test_public_url_allowed(monkeypatch):
    def fake_getaddrinfo(host, port):
        return [(2, 1, 6, "", ("1.1.1.1", 0))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert is_safe_external_url("https://example.com/data.zip")


def test_unresolvable_host_blocked(monkeypatch):
    def fake_getaddrinfo(host, port):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert not is_safe_external_url("https://not-a-real-domain-xyz.invalid/")

def test_ipv6_mapped_ipv4_blocked():
    """[STAGE4] SSRF: IPv6-mapped IPv4 (loopback + link-local) блокируются."""
    from services.url_safety import is_safe_external_url
    assert not is_safe_external_url("http://[::ffff:127.0.0.1]/")
    assert not is_safe_external_url("http://[::ffff:169.254.169.254]/")


def test_ipv6_mapped_public_still_allowed(monkeypatch):
    """[STAGE4] SSRF: ::ffff:1.1.1.1 (публичный) — разрешён."""
    import socket as _socket
    from services.url_safety import is_safe_external_url

    def fake_getaddrinfo(host, port):
        return [(10, 1, 6, "", ("::ffff:1.1.1.1", 0, 0, 0))]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)
    assert is_safe_external_url("http://[::ffff:1.1.1.1]/")
