"""
External Gemini agent for Microsoft Foundry observability.

Foundry matches traces by gen_ai.agent.id == OTEL_AGENT_ID.
"""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")
os.environ.setdefault(
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "SPAN_AND_EVENT"
)

CONNECTION_STRING = (
    os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    or os.getenv("AZURE_CONNECTION_STRING")
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AGENT_NAME = os.getenv("AGENT_NAME", "gemini-governance-agent")
OTEL_AGENT_ID = os.getenv("OTEL_AGENT_ID", f"{AGENT_NAME}-v1")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")


def _require_env() -> None:
    missing = [
        name
        for name, value in (
            ("APPLICATIONINSIGHTS_CONNECTION_STRING", CONNECTION_STRING),
            ("GEMINI_API_KEY", GEMINI_API_KEY),
        )
        if not value or str(value).startswith("YOUR_")
    ]
    if missing:
        print("Error: set real values in .env for: " + ", ".join(missing))
        sys.exit(1)


_require_env()

from microsoft.opentelemetry import use_microsoft_opentelemetry
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

use_microsoft_opentelemetry(
    enable_azure_monitor=True,
    azure_monitor_connection_string=CONNECTION_STRING,
    sampling_ratio=1.0,
    enable_sensitive_data=True,
    instrumentation_options={
        "langchain": {
            "enabled": True,
            "agent_id": OTEL_AGENT_ID,
            "agent_name": AGENT_NAME,
        },
    },
)

from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(
    model=GEMINI_MODEL,
    google_api_key=GEMINI_API_KEY,
)
tracer = trace.get_tracer(__name__)


def _messages_json(role: str, text: str, *, finish_reason: str | None = None) -> str:
    item: dict = {
        "role": role,
        "parts": [{"type": "text", "content": text}],
    }
    if finish_reason:
        item["finish_reason"] = finish_reason
    return json.dumps([item], ensure_ascii=False)


def _normalize_content(content) -> str:
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
            else:
                parts.append(str(block))
        return "".join(parts).strip()
    return str(content).strip()


def run_external_agent(user_prompt: str) -> str:
    """Call Gemini and emit a Foundry-visible invoke_agent span."""
    with tracer.start_as_current_span(
        "invoke_agent",
        kind=SpanKind.INTERNAL,
        attributes={
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.id": OTEL_AGENT_ID,
            "gen_ai.agent.name": AGENT_NAME,
            "gen_ai.system": "google_genai",
            "gen_ai.input.messages": _messages_json("user", user_prompt),
        },
    ) as root_span:
        try:
            result = llm.invoke(user_prompt)
            answer = _normalize_content(getattr(result, "content", result))
        except Exception as exc:
            root_span.record_exception(exc)
            root_span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise

        root_span.set_attribute(
            "gen_ai.output.messages",
            _messages_json("assistant", answer, finish_reason="stop"),
        )
        return answer


def flush_telemetry(timeout_millis: int = 30_000) -> bool:
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if not callable(force_flush):
        return False
    return bool(force_flush(timeout_millis=timeout_millis))
