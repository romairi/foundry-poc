"""
Register / verify the Gemini external agent in Microsoft Foundry (preview).

This does NOT run Gemini and does NOT create traces by itself.
It only creates a Foundry record that links traces via otel_agent_id.

Docs: https://learn.microsoft.com/azure/foundry/agents/how-to/register-external-agent
"""

import os
import sys

from dotenv import load_dotenv
from azure.core.exceptions import HttpResponseError, ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import ExternalAgentDefinition

load_dotenv()

FOUNDRY_PROJECT_ENDPOINT = (
    os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
)
AGENT_NAME = os.getenv("AGENT_NAME", "gemini-governance-agent")
OTEL_AGENT_ID = os.getenv("OTEL_AGENT_ID", f"{AGENT_NAME}-v1")
AGENT_DESCRIPTION = os.getenv(
    "AGENT_DESCRIPTION",
    "External Gemini agent (Google AI Studio) with OpenTelemetry to App Insights.",
)


def _print_version(agent_version) -> None:
    definition = agent_version.definition
    otel_id = getattr(definition, "otel_agent_id", None)
    print(f"OK — external agent registration works")
    print(f"  name:          {agent_version.name}")
    print(f"  version:       {agent_version.version}")
    print(f"  kind:          {getattr(definition, 'kind', None)}")
    print(f"  otel_agent_id: {otel_id}")
    print(
        "\nRegistration is metadata only. Traces appear only after you run agent.py "
        "and Foundry can read App Insights (needs Log Analytics Reader on the "
        "App Insights resource)."
    )


def main() -> None:
    if not FOUNDRY_PROJECT_ENDPOINT:
        print("Error: set FOUNDRY_PROJECT_ENDPOINT in .env")
        sys.exit(1)

    project = AIProjectClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )

    print(f"Project: {FOUNDRY_PROJECT_ENDPOINT}")
    print(f"Registering / verifying '{AGENT_NAME}' (otel_agent_id={OTEL_AGENT_ID})")

    try:
        # Prefer get — registration already succeeded earlier
        details = project.agents.get(agent_name=AGENT_NAME)
        latest = details.versions.latest
        print("Agent already exists in Foundry (no need to recreate).")
        _print_version(latest)
        expected = OTEL_AGENT_ID
        actual = getattr(latest.definition, "otel_agent_id", None)
        if actual != expected:
            print(
                f"\nWARNING: portal otel_agent_id={actual!r} != .env OTEL_AGENT_ID={expected!r}"
            )
            print("Update Edit OTel AgentID in Foundry or change .env to match.")
        return
    except HttpResponseError as exc:
        if getattr(exc, "status_code", None) not in (404,):
            # Fall through to create only when missing
            if "not found" not in str(exc).lower() and "NotFound" not in str(exc):
                pass

    try:
        agent_version = project.agents.create_version(
            agent_name=AGENT_NAME,
            description=AGENT_DESCRIPTION,
            definition=ExternalAgentDefinition(otel_agent_id=OTEL_AGENT_ID),
        )
        _print_version(agent_version)
    except (ResourceExistsError, HttpResponseError) as exc:
        print(f"Create failed ({exc}). Trying get...")
        details = project.agents.get(agent_name=AGENT_NAME)
        _print_version(details.versions.latest)


if __name__ == "__main__":
    main()
