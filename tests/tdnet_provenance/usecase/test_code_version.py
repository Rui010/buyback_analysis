import subprocess
from types import SimpleNamespace

import pytest

from tdnet_provenance.usecase.code_version import CodeVersionError, resolve_code_commit

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _git_ok(output):
    def run(*args, **kwargs):
        return SimpleNamespace(stdout=output + "\n")

    return run


def _git_fail(*args, **kwargs):
    raise subprocess.CalledProcessError(128, "git")


def test_injected_code_commit_has_priority():
    assert resolve_code_commit(env={"CODE_COMMIT": COMMIT.upper()}, run=_git_fail) == COMMIT


def test_falls_back_to_git_head():
    assert resolve_code_commit(env={}, run=_git_ok(COMMIT)) == COMMIT


@pytest.mark.parametrize("value", ["unknown", "abc123", "g" * 40])
def test_rejects_unstable_or_short_injected_value(value):
    with pytest.raises(CodeVersionError):
        resolve_code_commit(env={"CODE_COMMIT": value}, run=_git_ok(COMMIT))


def test_raises_when_no_source_available():
    with pytest.raises(CodeVersionError):
        resolve_code_commit(env={}, run=_git_fail)


def test_raises_when_git_is_not_installed():
    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    with pytest.raises(CodeVersionError):
        resolve_code_commit(env={}, run=missing)
