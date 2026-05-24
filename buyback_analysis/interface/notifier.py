import logging
import os

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

_logger = logging.getLogger("buyback_analysis")

_client: WebClient | None = None


def _get_client() -> WebClient | None:
    global _client
    token = os.getenv("SLACK_TOKEN")
    if not token:
        return None
    if _client is None:
        _client = WebClient(token)
    return _client


def notify_success(script_name: str, detail: str = "") -> None:
    """処理成功をSlackに通知する。SLACK_TOKENが未設定の場合は何もしない。"""
    message = f"成功 - {script_name}"
    if detail:
        message += f"\n{detail}"
    _post(message)


def notify_error(script_name: str, detail: str = "") -> None:
    """処理失敗をSlackに通知する。SLACK_MENTIONが設定されていればメンション付きで送信する。"""
    mention = os.getenv("SLACK_MENTION", "")
    prefix = f"{mention} " if mention else ""
    message = f"{prefix}データの取得に失敗しました - {script_name}"
    if detail:
        message += f"\n{detail}"
    _post(message)


def _post(message: str) -> None:
    client = _get_client()
    if client is None:
        return
    channel = os.getenv("SLACK_CHANNEL", "")
    if not channel:
        return
    try:
        client.chat_postMessage(channel=channel, text=message)
    except SlackApiError as e:
        _logger.error(f"Slack通知に失敗しました: {e.response['error']}")
