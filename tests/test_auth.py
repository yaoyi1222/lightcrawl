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
