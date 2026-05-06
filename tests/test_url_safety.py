from unittest.mock import patch

import pytest

from refetch.errors import ErrorCode, FetchError
from refetch.url_safety import domain_matches, etld1, validate_url


def test_etld1_basic():
    assert etld1("https://x.com/foo") == "x.com"
    assert etld1("https://api.x.com/v2") == "x.com"
    assert etld1("https://foo.bar.example.co.uk/") == "example.co.uk"


def test_domain_matches():
    assert domain_matches("https://api.x.com/v2", "x.com")
    assert not domain_matches("https://attacker.com/x.com", "x.com")


def test_validate_rejects_non_http():
    with pytest.raises(FetchError) as ei:
        validate_url("file:///etc/passwd")
    assert ei.value.code == ErrorCode.URL_NOT_ALLOWED


def test_validate_rejects_loopback():
    with patch("refetch.url_safety.socket.gethostbyname", return_value="127.0.0.1"):
        with pytest.raises(FetchError) as ei:
            validate_url("http://localhost/admin")
        assert ei.value.code == ErrorCode.URL_NOT_ALLOWED


def test_validate_rejects_private_net():
    with patch("refetch.url_safety.socket.gethostbyname", return_value="10.0.0.5"):
        with pytest.raises(FetchError) as ei:
            validate_url("http://internal.example/")
        assert ei.value.code == ErrorCode.URL_NOT_ALLOWED


def test_validate_rejects_metadata_ip():
    with patch("refetch.url_safety.socket.gethostbyname", return_value="169.254.169.254"):
        with pytest.raises(FetchError):
            validate_url("http://metadata.example/")


def test_validate_allows_public():
    with patch("refetch.url_safety.socket.gethostbyname", return_value="93.184.216.34"):
        r = validate_url("https://example.com/foo")
        assert r.hostname == "example.com"
        assert r.etld1 == "example.com"
