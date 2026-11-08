"""自己株買いの判定・抽出結果の書き込み。

通常時は従来どおりpost_url / update_parse_status / post_dataで即時に書く。
RERUN時は旧結果を削除せず、判定した文書種別を保持しておき、結果が確定した時点で
is_checkedとIRテーブルの行を1つの版として採用する（tdnet_provenance.usecase.adopt_result）。
抽出に失敗した場合は旧結果に触れない。
"""

from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.correction import Correction
from buyback_analysis.models.is_checked import IsChecked
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.retirement import Retirement
from buyback_analysis.usecase.post_data import post_data
from buyback_analysis.usecase.post_url import post_url, update_parse_status
from tdnet_provenance.usecase.adopt_result import adopt_result

BUYBACK_RESULT_TYPE = "buyback"
# 先頭がparse_statusを持つ主テーブル
BUYBACK_TABLES = (IsChecked, Announcement, Progress, Completion, Correction, Retirement)


class BuybackResultWriter:
    def __init__(self, session, *, rerun: bool):
        self.session = session
        self.rerun = rerun
        self._detected: dict[str, tuple[str, str]] = {}  # url -> (code, detected_type)

    def register_type(self, code: str, url: str, detected_type: str) -> None:
        """文書種別の判定結果。RERUN時は採用まで保存しない。"""
        if self.rerun:
            self._detected[url] = (code, detected_type)
        else:
            post_url(self.session, code, url, detected_type)

    def _adopt(self, url: str, status: str, obj: dict | None) -> bool:
        code, detected_type = self._detected[url]

        def write() -> bool:
            self.session.add(IsChecked(code=code, url=url, detected_type=detected_type, parse_status=status))
            self.session.flush()
            return obj is None or post_data(self.session, obj, commit=False)

        return adopt_result(
            self.session, result_type=BUYBACK_RESULT_TYPE, tables=BUYBACK_TABLES, url=url, code=code,
            extraction_status=status, run_ids=[], write_current=write, status_column="parse_status",
        )

    def mark(self, url: str, status: str) -> None:
        """parse_statusの更新。RERUN時はskipped（判定結果が対象外）だけを版として採用し、
        failedは旧結果を維持するため何もしない（savedはsave()で確定済み）。"""
        if not self.rerun:
            update_parse_status(self.session, url, status)
        elif status == "skipped":
            self._adopt(url, "skipped", None)

    def save(self, url: str, obj: dict) -> bool:
        """抽出結果の保存。通常時はpost_dataの例外をそのまま送出する（従来どおり）。"""
        if not self.rerun:
            return post_data(self.session, obj)
        return self._adopt(url, "saved", obj)
