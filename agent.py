"""
External Gemini agent traced exactly as Microsoft Foundry docs require:
microsoft-opentelemetry + LangChain instrumentation with agent_id.

Foundry matches traces by gen_ai.agent.id == OTEL_AGENT_ID from registration.
Docs: https://learn.microsoft.com/azure/foundry/agents/how-to/register-external-agent
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# GenAI content capture (Foundry / Microsoft OTel docs)
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

# IMPORTANT: configure OTel BEFORE importing LangChain runnable code paths
from microsoft.opentelemetry import use_microsoft_opentelemetry
from opentelemetry import trace

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


def run_external_agent(user_prompt: str) -> str:
    """Run one LangChain Gemini call (auto-traced by microsoft-opentelemetry)."""
    result = llm.invoke(user_prompt)
    content = getattr(result, "content", result)
    if isinstance(content, list):
        # Some LC message formats return a list of content blocks
        parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
            else:
                parts.append(str(block))
        return "".join(parts).strip()
    return str(content).strip()


def _flush_telemetry() -> bool:
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if not callable(force_flush):
        print("Telemetry flush: provider has no force_flush")
        return False
    ok = bool(force_flush(timeout_millis=30000))
    print(f"Telemetry flush to Application Insights: {'OK' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    prompt = "Say hello in one short sentence."
    print(f"Agent: {AGENT_NAME}")
    print(f"OTEL agent id: {OTEL_AGENT_ID}")
    print(f"Model: {GEMINI_MODEL}")
    print(f"Prompt: {prompt}\n")
    try:
        print(f"Gemini response:\n{run_external_agent(prompt)}")
    finally:
        flushed = _flush_telemetry()
        if flushed:
            print(
                "\nWait 2–5 minutes, then refresh Foundry → Agents → "
                f"{AGENT_NAME} → Traces"
            )
            print(f"Confirm Edit OTel AgentID = {OTEL_AGENT_ID}")
        else:
            print("\nWARNING: flush failed. Check APPLICATIONINSIGHTS_CONNECTION_STRING.")
