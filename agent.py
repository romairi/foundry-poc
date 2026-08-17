"""יועץ הלוואות חכם: מאגר מדומה + Microsoft Foundry (gpt-5-mini)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from data.mock_loans import (
    evaluate_loan,
    get_loan_by_client_id,
    search_loans_by_name,
)
from prompts.agent_prompts import SYSTEM_PROMPT, format_loan_card

FOUNDRY_PROJECT_ENDPOINT = (
    os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
)
MODEL_DEPLOYMENT_NAME = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5-mini")
AGENT_NAME = os.getenv("AGENT_NAME", "hebrew-loan-advisor")

_CLIENT_ID_RE = re.compile(r"\bIL-\d{4}\b", re.IGNORECASE)
_openai_client = None


def _collect_context(user_prompt: str) -> dict[str, Any]:
    ids = _CLIENT_ID_RE.findall(user_prompt or "")
    records = []
    for cid in ids:
        row = get_loan_by_client_id(cid)
        if row:
            records.append(row)
    if not records:
        records = search_loans_by_name(user_prompt)
    evaluations = [evaluate_loan(r) for r in records]
    return {"records": records, "evaluations": evaluations}


def _fallback_hebrew_reply(ctx: dict[str, Any]) -> str:
    records = ctx["records"]
    if not records:
        return (
            "לא מצאתי לקוח מתאים במאגר. "
            "אפשר לציין מספר לקוח (למשל IL-1001) או שם מלא כמו דוד כהן."
        )
    parts = ["להלן ממצאי המערכת (החלטה סופית בידי הבנקאי):"]
    for rec, ev in zip(records, ctx["evaluations"], strict=False):
        parts.append(format_loan_card(rec))
        parts.append(f"המלצת מערכת: {ev['המלצת_מערכת']}. {ev['נימוק']}")
    return "\n\n".join(parts)


def _get_foundry_openai():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    if not FOUNDRY_PROJECT_ENDPOINT:
        raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT is not set")
    from azure.identity import DefaultAzureCredential
    from azure.ai.projects import AIProjectClient

    project = AIProjectClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )
    _openai_client = project.get_openai_client()
    return _openai_client


def _call_foundry(user_prompt: str, ctx: dict[str, Any]) -> str:
    payload = {
        "שאלה_המשתמש": user_prompt,
        "רשומות_מהמאגר": ctx["records"],
        "הערכת_מערכת": ctx["evaluations"],
    }
    user_content = (
        "נתוני מאגר (JSON):\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nענה בעברית מקצועית על סמך הנתונים בלבד."
    )
    client = _get_foundry_openai()
    completion = client.chat.completions.create(
        model=MODEL_DEPLOYMENT_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    return (completion.choices[0].message.content or "").strip()


def run_external_agent(user_prompt: str) -> str:
    """תשובה בעברית דרך gpt-5-mini ב-Foundry."""
    ctx = _collect_context(user_prompt)
    try:
        text = _call_foundry(user_prompt, ctx)
        return text or _fallback_hebrew_reply(ctx)
    except Exception:
        # Local/dev without az login still returns Hebrew from mock rules.
        return _fallback_hebrew_reply(ctx)
