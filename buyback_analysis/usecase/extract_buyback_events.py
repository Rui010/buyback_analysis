"""Gemini text extraction for Phase 1 multi-event buyback documents."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError
from pydantic import ValidationError

from buyback_analysis.consts.llm_model import LlmModel
from buyback_analysis.interface.load_prompt_template import load_prompt_template
from buyback_analysis.interface.llm_usage import report_llm_response
from buyback_analysis.interface.logger import Logger
from buyback_analysis.usecase.event_schemas import (
    BuybackEventExtraction,
    LlmBuybackEventExtraction,
    strict_extraction_from_transport,
)


logger = Logger()
PROMPT_FILENAME = "buyback_events.md"
GENERATION_CONFIG = {
    "response_mime_type": "application/json",
    "response_schema": LlmBuybackEventExtraction,
    "temperature": 0,
    "max_output_tokens": 16384,
}
EXTRACTOR_VERSION = "buyback_events_text:3"


def extract_buyback_events(
    title: str, content: str, code: str, name: str
) -> Optional[BuybackEventExtraction]:
    """Extract all independent events in one document; return None on invalid output."""

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません")
    prompt = load_prompt_template(
        PROMPT_FILENAME, title=title, content=content, code=code, name=name
    )
    max_retries = 3
    retry_delay = 60
    for attempt in range(1, max_retries + 1):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=LlmModel.LLM_MODEL_GEMINI.value,
                contents=prompt,
                config=GENERATION_CONFIG,
            )
            report_llm_response(response)
            if response.text is None:
                logger.error("[BuybackEvents] response.textがありません")
                return None
            cleaned = re.sub(
                r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL
            )
            transport = LlmBuybackEventExtraction.model_validate(json.loads(cleaned))
            return strict_extraction_from_transport(transport)
        except APIError as exc:
            if exc.code in {502, 503, 504} and attempt < max_retries:
                logger.info(
                    f"[BuybackEvents] サーバーエラー {exc.code}。"
                    f"リトライ {attempt}/{max_retries}"
                )
                time.sleep(retry_delay)
                continue
            raise
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.error(f"[BuybackEvents] 抽出結果を検証できません: {exc}")
            return None
