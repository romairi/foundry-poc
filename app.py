"""HTTP API for local test and container deploy (APIM backend)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import AGENT_NAME, GEMINI_MODEL, OTEL_AGENT_ID, run_external_agent

logger = logging.getLogger(__name__)

app = FastAPI(title="Gemini External Agent", version="1.0.0")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32_000)


class ChatResponse(BaseModel):
    reply: str
    agent_name: str
    otel_agent_id: str
    model: str


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": AGENT_NAME,
        "health": "/health",
        "chat": "POST /v1/chat",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/v1/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    try:
        reply = run_external_agent(body.message)
    except Exception as exc:
        logger.exception("Agent invocation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(
        reply=reply,
        agent_name=AGENT_NAME,
        otel_agent_id=OTEL_AGENT_ID,
        model=GEMINI_MODEL,
    )
