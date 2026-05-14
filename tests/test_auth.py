import pytest

from refetch import auth
from refetch.errors import ErrorCode, FetchError


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("refetch.auth.PROFILES", tmp_path)


def test_save_and_load_profile(tmp_path):
    state = {"cookies": [{"name": "x", "value": "y"}], "origins": []}
    meta = auth.save_profile("twitter", state, "x.com")
    assert meta.bound_domain == "x.com"
    assert (tmp_path / "twitter.json").stat().st_mode & 0o777 == 0o600
    loaded = auth.load_storage_state("twitter")
    assert loaded == state


def test_invalid_profile_name():
    with pytest.raises(FetchError) as ei:
        auth.save_profile("Bad Name!", {}, "x.com")
    assert ei.value.code == ErrorCode.URL_NOT_ALLOWED


def test_revoke_removes_files(tmp_path):
    auth.save_profile("foo", {}, "example.com")
    assert (tmp_path / "foo.json").exists()
    assert auth.revoke_profile("foo") is True
    assert not (tmp_path / "foo.json").exists()
    assert not (tmp_path / "foo.meta.json").exists()
    assert auth.revoke_profile("foo") is False  # idempotent


def test_list_profiles_empty():
    assert auth.list_profiles() == []


def test_get_missing_profile():
    with pytest.raises(FetchError) as ei:
        auth.get_profile("nope")
    assert ei.value.code == ErrorCode.PROFILE_NOT_FOUND


def test_find_free_port_returns_bindable_port():
    """The returned port must be one we can actually bind to."""
    import socket as _socket
    port = auth._find_free_port(start=49152, span=100)  # use the ephemeral range
    assert 49152 <= port < 49252
    # The port should be available — i.e. binding it succeeds.
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


def test_find_free_port_skips_occupied(monkeypatch):
    """If `start` is already taken, the helper must walk forward."""
    import socket as _socket
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    occupied = sock.getsockname()[1]
    sock.listen(1)
    try:
        port = auth._find_free_port(start=occupied, span=20)
        assert port != occupied
        assert occupied < port < occupied + 20
    finally:
        sock.close()


def test_find_chrome_returns_string_or_raises(monkeypatch):
    """On systems without Chrome we should get a clear FetchError, not a
    silent `None` that breaks downstream subprocess.Popen with EFAULT."""
    monkeypatch.setattr("refetch.auth.shutil.which", lambda name: None)
    monkeypatch.setattr("refetch.auth.sys.platform", "linux")
    with pytest.raises(FetchError) as ei:
        auth._find_chrome()
    assert ei.value.code == ErrorCode.UNKNOWN
    assert "chrome" in ei.value.detail.lower() or "chromium" in ei.value.detail.lower()


def test_find_chrome_uses_shutil_which_on_linux(monkeypatch):
    monkeypatch.setattr("refetch.auth.sys.platform", "linux")
    monkeypatch.setattr(
        "refetch.auth.shutil.which",
        lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None,
    )
    assert auth._find_chrome() == "/usr/bin/google-chrome"


def test_check_cdp_pages_handles_unreachable_port():
    """Polling a closed port should return None, never raise."""
    result = auth._check_cdp_pages(1)  # port 1 is essentially never open
    assert result is None


def test_check_cdp_pages_parses_json_payload(monkeypatch):
    import httpx

    class FakeResp:
        status_code = 200
        text = '[{"url": "https://x.com/login"}]'
        def json(self):
            import json as _j
            return _j.loads(self.text)

    monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResp())
    out = auth._check_cdp_pages(9999)
    assert out == [{"url": "https://x.com/login"}]


def test_check_cdp_pages_ignores_non_json_response(monkeypatch):
    import httpx

    class FakeResp:
        status_code = 200
        text = "not-json"

    monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResp())
    assert auth._check_cdp_pages(9999) is None
