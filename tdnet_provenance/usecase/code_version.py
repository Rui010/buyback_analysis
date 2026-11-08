"""processing runに記録する実行コード版の解決（tdnet-provenance-v1 §4.4）。

優先順位: 環境変数 CODE_COMMIT → Git checkoutの HEAD。
build manifest・artifact-sha256 は本番の反映方法を確認するまで実装しない
（どちらも取得できなければ例外にし、unknown等の不安定な値は使わない）。
"""

import os
import re
import subprocess
from pathlib import Path

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPO_ROOT = Path(__file__).resolve().parents[2]


class CodeVersionError(RuntimeError):
    pass


def resolve_code_commit(env=None, repo_dir=REPO_ROOT, run=subprocess.run) -> str:
    env = os.environ if env is None else env
    injected = (env.get("CODE_COMMIT") or "").strip().lower()
    if injected:
        if not COMMIT_PATTERN.fullmatch(injected):
            raise CodeVersionError(f"CODE_COMMITは40桁のGit commit IDを指定してください: {injected}")
        return injected

    try:
        completed = run(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CodeVersionError("CODE_COMMITが未設定で、Git checkoutからHEADも取得できません") from exc
    head = completed.stdout.strip().lower()
    if not COMMIT_PATTERN.fullmatch(head):
        raise CodeVersionError(f"git rev-parse HEADの結果が不正です: {head}")
    return head
