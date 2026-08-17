"""שירות HTTP ליועץ ההלוואות. UTF-8 מפורש, נתיבי AML ו-APIM."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent import AGENT_NAME, MODEL_DEPLOYMENT_NAME, run_external_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")


app = FastAPI(
    title="יועץ הלוואות חכם",
    version="1.0.0",
    default_response_class=UTF8JSONResponse,
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32_000)


class ChatResponse(BaseModel):
    reply: str
    agent_name: str
    model: str
    language: str = "he"


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": AGENT_NAME,
        "language": "he",
        "health": "/health",
        "chat": "POST /v1/chat",
        "score": "POST /score",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME, "language": "he"}


@app.post("/v1/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    try:
        reply = run_external_agent(body.message)
    except Exception as exc:
        logger.exception("קריאת הסוכן נכשלה")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(reply=reply, agent_name=AGENT_NAME, model=MODEL_DEPLOYMENT_NAME)


@app.post("/score")
def score(payload: dict[str, Any]) -> dict[str, Any]:
    """Azure ML online-endpoint invoke."""
    message = (
        payload.get("message")
        or payload.get("input")
        or (payload.get("input_data") or {}).get("message")
        or ""
    )
    if isinstance(payload.get("input_data"), dict) and not message:
        data = payload["input_data"].get("data")
        if isinstance(data, list) and data:
            first = data[0]
            message = first if isinstance(first, str) else json.dumps(first, ensure_ascii=False)
    if not str(message).strip():
        raise HTTPException(status_code=400, detail="חסרה הודעת משתמש בשדה message")
    try:
        reply = run_external_agent(str(message))
    except Exception as exc:
        logger.exception("קריאת /score נכשלה")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply, "agent_name": AGENT_NAME, "language": "he"}
