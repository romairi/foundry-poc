"""
agents_config.py

Multi-agent configuration for the SmartLoan system, built on the Azure AI
Agent SDK (`azure-ai-agents`).

Three agents are created on the Azure AI Foundry project, each on the model
best suited to its job (mixing vendors from the Foundry model catalog):

1. Orchestrator Agent (the "brain" + the math) - model: gpt-5.6-sol (OpenAI)
   The only agent that talks to the user. It has two local Function Tools:
   `get_customer_financials` and `ask_policy_agent` (the latter forwards the
   question to the Policy Agent below and returns its answer). It does the
   DTI/LTV/credit-tier math itself (needs a strong reasoning + tool-calling
   model).

   NOTE: we deliberately do NOT use the SDK's `ConnectedAgentTool` here. In
   testing against this project, ANY agent-to-agent call made through
   `ConnectedAgentTool` failed immediately with a generic
   `{"code": "server_error", "message": "Sorry, something went wrong."}` —
   reproduced even between two agents on the exact same OpenAI model, so it's
   a platform/project-level limitation, not a model or code issue. Calling the
   Policy Agent as a plain local Function Tool (same mechanism as
   `get_customer_financials`) sidesteps that entirely and works with any
   model/vendor combination.

2. Policy Agent (RAG) - model: Cohere-command-a-plus-05-2026 (Cohere)
   Attached to a Vector Store built from `bank_underwriting_policy_2026.pdf`.
   Answers questions about DTI/LTV limits, credit score tiers, and the
   High-Tech Exception using File Search (vector retrieval) over the PDF.
   Requires tool-calling support (needed to invoke File Search).

3. Fast Router (greeting / FAQ triage) - model: DeepSeek-V4-Flash (DeepSeek)
   A cheap, fast first point of contact for `telegram_bot.py`. It classifies
   an incoming message as either answerable directly (small talk, generic
   "how does this bot work" questions) or as needing the full Orchestrator
   pipeline. This model does NOT support tool calling, so the Fast Router
   has no tools - it only returns a small JSON verdict, never touches
   customer data or policy numbers itself.

Agent IDs are cached locally in `.agents_cache.json` so that restarting the
bot re-uses existing agents/vector stores instead of recreating them (and
spamming your Foundry project) on every run.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    Agent,
    FilePurpose,
    FileSearchTool,
    FunctionTool,
)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from mock_database import get_customer_financials

load_dotenv()
logger = logging.getLogger(__name__)

# --- Configuration -----------------------------------------------------------

ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT")

# Each agent runs on its own deployment name (each must already be deployed in
# your Foundry project). Falls back to the legacy single MODEL_DEPLOYMENT_NAME
# var, then to a safe default, so existing setups keep working.
_legacy_default = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4o")
ORCHESTRATOR_MODEL = os.getenv("ORCHESTRATOR_MODEL", _legacy_default)
POLICY_MODEL = os.getenv("POLICY_MODEL", _legacy_default)
ROUTER_MODEL = os.getenv("ROUTER_MODEL", _legacy_default)

POLICY_PDF_PATH = Path(__file__).parent / "bank_underwriting_policy_2026.pdf"
CACHE_PATH = Path(__file__).parent / ".agents_cache.json"

POLICY_AGENT_NAME = "policy_agent"
FAST_ROUTER_AGENT_NAME = "fast_router_agent"
ORCHESTRATOR_AGENT_NAME = "orchestrator_agent"

POLICY_AGENT_INSTRUCTIONS = """You are the Policy Agent for H-Bank's SmartLoan system.

You have File Search access to the official "H-Bank Underwriting Policy 2026" document.
Your ONLY job is to answer precise questions about underwriting rules by retrieving them
from that document, such as:
- DTI (Debt-to-Income) limits, including the stricter limit for low credit scores.
- LTV (Loan-to-Value) limits for mortgages (first-time buyers vs. investment properties).
- Credit score tiers and what each tier means (auto-approval, standard, manual check, decline).
- The "High-Tech Exception" (relaxed employment tenure requirement) and who qualifies.

Rules:
- Always answer using the retrieved document content, not general knowledge.
- Be precise and quote the exact numeric thresholds (percentages, scores, months, amounts).
- If a rule is not covered by the document, say so explicitly instead of guessing.
- Keep answers short, structured, and easy for another agent to parse and use in a calculation.
"""

ORCHESTRATOR_INSTRUCTIONS = """You are "SmartLoan Assistant", the friendly Telegram-facing loan
officer AND financial analyst for H-Bank. You coordinate the whole system AND do the math
yourself, and you always answer in the SAME language the user wrote in (Hebrew, Russian or
English).

You have two tools:
- get_customer_financials: fetch the user's financial profile from the bank database using
  their Telegram ID. ALWAYS call this first when discussing a specific application.
- ask_policy_agent: ask about H-Bank's underwriting rules (DTI/LTV limits, credit score tiers,
  the High-Tech Exception). ALWAYS call this to learn the exact limits BEFORE doing any math —
  never rely on memorized thresholds, since bank policy can change.

Standard workflow for a loan question:
1. Call get_customer_financials with the user's Telegram ID.
   - If status is "unknown_customer", ask the user to provide their details manually (age,
     profession, monthly net income, existing debts, credit score, loan type, requested
     amount, property value, down payment) before continuing.
2. Call ask_policy_agent to retrieve the DTI limit, LTV limit and credit score tiers that
   apply. If the customer's profession looks tech-related (e.g. Software Engineer, Developer,
   Data Scientist) and their income is above 20,000 ₪, also ask about the High-Tech Exception.
   Employment tenure is NOT in the database — if it matters for the decision, ask the user
   directly instead of guessing.
3. Do the math yourself, showing your work clearly:
   - DTI% = existing_debt_payments / monthly_net_income * 100.
     Note: if no loan term/interest rate is available to estimate the NEW loan's monthly
     payment, compute DTI on existing obligations only and explicitly say this is a
     simplification.
   - LTV% = requested_amount / property_value * 100 (mortgages only; "N/A" for consumer loans
     not secured by property).
   - Determine the credit score tier using the tiers policy_agent gave you.
   - Compare each metric against the limits from step 2 and mark PASS or FAIL.
4. Reply to the user with a clear, friendly, well-formatted summary: their key numbers (DTI%,
   LTV%, credit tier), whether they pass each check, and an overall recommendation
   (Auto-Approve / Standard Review / Manual Check / Decline). Use short sections and emoji
   sparingly for readability (✅ / ⚠️ / ❌).

If the user is just chatting or asking general questions, answer helpfully without forcing the
full workflow. Never invent numbers — only use what the tools return.
"""

FAST_ROUTER_INSTRUCTIONS = """You are the Fast Router for H-Bank's SmartLoan Telegram bot: a
lightweight first point of contact whose only job is to triage incoming messages FAST and
cheaply, before they might reach the much more expensive Orchestrator pipeline.

You have NO tools and NO access to customer data or bank policy documents. Respond in the SAME
language the user wrote in (Hebrew, Russian or English).

You must ALWAYS answer with ONLY a single JSON object — no markdown, no code fences, no extra
text before or after it — in exactly this shape:
{"route": "direct", "reply": "<short friendly answer>"}
or
{"route": "orchestrator", "reply": null}

Use "route": "direct" ONLY for:
- Greetings, thanks, goodbyes, small talk.
- Generic meta-questions about how the bot works (e.g. "what can you do?").

Use "route": "orchestrator" for EVERYTHING else, including:
- Any question about loan eligibility, mortgages, DTI, LTV, credit score, interest rates.
- Any request that needs the user's personal financial data or exact bank policy numbers.
- Anything you are not 100% sure is safe to answer without the specialist agents, since only
  they have access to the real policy document and the customer database.
When in doubt, always choose "orchestrator" rather than guessing or making up numbers.
"""


def get_agents_client() -> AgentsClient:
    if not ENDPOINT:
        raise RuntimeError(
            "AZURE_AI_PROJECT_ENDPOINT is not set. Add it to your .env file."
        )
    return AgentsClient(endpoint=ENDPOINT, credential=DefaultAzureCredential())


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not parse %s, starting with a fresh cache.", CACHE_PATH.name)
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def _agent_is_alive(client: AgentsClient, agent_id: Optional[str]) -> bool:
    if not agent_id:
        return False
    try:
        client.get_agent(agent_id)
        return True
    except Exception:
        return False


def _ensure_policy_agent(client: AgentsClient, cache: dict) -> Agent:
    cached_id = cache.get("policy_agent_id")
    if _agent_is_alive(client, cached_id):
        print(f"✓ Reusing Policy Agent (id: {cached_id})")
        return client.get_agent(cached_id)

    if not POLICY_PDF_PATH.exists():
        raise FileNotFoundError(f"Policy document not found at '{POLICY_PDF_PATH}'.")

    print("📄 Uploading underwriting policy PDF and building the vector store (RAG)...")
    uploaded_file = client.files.upload_and_poll(
        file_path=str(POLICY_PDF_PATH), purpose=FilePurpose.AGENTS
    )
    vector_store = client.vector_stores.create_and_poll(
        file_ids=[uploaded_file.id], name="bank_underwriting_policy_store"
    )
    file_search = FileSearchTool(vector_store_ids=[vector_store.id])

    agent = client.create_agent(
        model=POLICY_MODEL,
        name=POLICY_AGENT_NAME,
        instructions=POLICY_AGENT_INSTRUCTIONS,
        tools=file_search.definitions,
        tool_resources=file_search.resources,
    )
    cache["file_id"] = uploaded_file.id
    cache["vector_store_id"] = vector_store.id
    cache["policy_agent_id"] = agent.id
    _save_cache(cache)
    print(f"✓ Policy Agent created (id: {agent.id})")
    return agent


def _ensure_fast_router_agent(client: AgentsClient, cache: dict) -> Agent:
    cached_id = cache.get("fast_router_agent_id")
    if _agent_is_alive(client, cached_id):
        print(f"✓ Reusing Fast Router Agent (id: {cached_id})")
        return client.get_agent(cached_id)

    # No tools on purpose: ROUTER_MODEL (e.g. DeepSeek-V4-Flash) does not support
    # tool calling, and the router shouldn't touch customer data or policy anyway.
    agent = client.create_agent(
        model=ROUTER_MODEL,
        name=FAST_ROUTER_AGENT_NAME,
        instructions=FAST_ROUTER_INSTRUCTIONS,
    )
    cache["fast_router_agent_id"] = agent.id
    _save_cache(cache)
    print(f"✓ Fast Router Agent created (id: {agent.id})")
    return agent


# Populated by _ensure_orchestrator_agent() so the module-level `ask_policy_agent`
# function (registered as a Function Tool) knows which client/agent to forward
# questions to. See module docstring for why this replaces ConnectedAgentTool.
_policy_agent_ref: dict = {"client": None, "agent_id": None}


def ask_policy_agent(question: str) -> str:
    """
    Ask the Policy Agent a question about H-Bank's underwriting rules.

    Forwards the question to the Policy Agent, which has File Search (RAG) access
    to the official underwriting policy PDF, and returns its answer. Use this to
    learn exact DTI/LTV limits, credit score tiers, or High-Tech Exception rules
    before doing any math — never rely on memorized thresholds.

    :param question: A specific policy question, e.g. "What is the DTI limit for
        a credit score of 600?" or "What is the High-Tech Exception?".
    :return: The Policy Agent's answer as plain text.
    """
    client: Optional[AgentsClient] = _policy_agent_ref["client"]
    agent_id: Optional[str] = _policy_agent_ref["agent_id"]
    if not client or not agent_id:
        return "Policy Agent is not initialized yet."

    try:
        thread = client.threads.create()
        client.messages.create(thread_id=thread.id, role="user", content=question)
        run = client.runs.create_and_process(thread_id=thread.id, agent_id=agent_id)

        if run.status == "failed":
            return f"Policy Agent error: {run.last_error}"

        for msg in client.messages.list(thread_id=thread.id):
            if msg.role == "assistant":
                for item in msg.content:
                    if hasattr(item, "text"):
                        return item.text.value
        return "Policy Agent returned no answer."
    except Exception as exc:  # keep the Orchestrator's run alive on sub-call errors
        logger.warning("ask_policy_agent failed: %s", exc)
        return f"Policy Agent is temporarily unavailable ({exc})."


def _ensure_orchestrator_agent(client: AgentsClient, cache: dict, policy_agent: Agent) -> Agent:
    _policy_agent_ref["client"] = client
    _policy_agent_ref["agent_id"] = policy_agent.id

    # The local function tools must be (re-)registered on the client regardless
    # of whether the orchestrator agent itself is freshly created or reused.
    client.enable_auto_function_calls({get_customer_financials, ask_policy_agent})

    cached_id = cache.get("orchestrator_agent_id")
    if _agent_is_alive(client, cached_id):
        print(f"✓ Reusing Orchestrator Agent (id: {cached_id})")
        return client.get_agent(cached_id)

    function_tool = FunctionTool({get_customer_financials, ask_policy_agent})

    agent = client.create_agent(
        model=ORCHESTRATOR_MODEL,
        name=ORCHESTRATOR_AGENT_NAME,
        instructions=ORCHESTRATOR_INSTRUCTIONS,
        tools=list(function_tool.definitions),
    )
    cache["orchestrator_agent_id"] = agent.id
    _save_cache(cache)
    print(f"✓ Orchestrator Agent created (id: {agent.id})")
    return agent


@dataclass
class SmartLoanAgents:
    """Bundle of the 3 live agents plus convenience methods to talk to them."""

    client: AgentsClient
    orchestrator: Agent
    policy_agent: Agent
    fast_router: Agent

    def route(self, message: str) -> dict:
        """
        Ask the Fast Router to triage a message: answer it directly (greeting/FAQ)
        or flag that it needs the full Orchestrator pipeline. Stateless — always
        runs on a fresh, throwaway thread since the router holds no conversation
        memory. Returns {"route": "direct"|"orchestrator", "reply": str|None}.
        Fails safe: any error or unparseable output routes to the Orchestrator.
        """
        try:
            thread = self.client.threads.create()
            self.client.messages.create(thread_id=thread.id, role="user", content=message)
            run = self.client.runs.create_and_process(
                thread_id=thread.id, agent_id=self.fast_router.id
            )

            if run.status == "failed":
                logger.warning("Fast Router run failed (%s); routing to Orchestrator", run.last_error)
                return {"route": "orchestrator", "reply": None}

            for msg in self.client.messages.list(thread_id=thread.id):
                if msg.role == "assistant":
                    for item in msg.content:
                        if hasattr(item, "text"):
                            return _parse_router_output(item.text.value)
        except Exception as exc:  # routing must never block a real answer
            logger.warning("Fast Router error (%s); routing to Orchestrator", exc)

        return {"route": "orchestrator", "reply": None}

    def ask(self, thread_id: Optional[str], message: str) -> Tuple[str, str]:
        """
        Send a message to the Orchestrator Agent on the given thread (creating a
        new one if `thread_id` is None), and return (response_text, thread_id).
        """
        if not thread_id:
            thread = self.client.threads.create()
            thread_id = thread.id
            print(f"🧵 New thread started: {thread_id}")

        self.client.messages.create(thread_id=thread_id, role="user", content=message)

        print(f"🚀 Running Orchestrator on thread {thread_id}...")
        run = self.client.runs.create_and_process(
            thread_id=thread_id, agent_id=self.orchestrator.id
        )

        if run.status == "failed":
            print(f"❌ Run failed: {run.last_error}")
            raise RuntimeError(f"Agent run failed: {run.last_error}")

        self._print_tool_trace(thread_id, run.id)

        for msg in self.client.messages.list(thread_id=thread_id):
            if msg.role == "assistant":
                for item in msg.content:
                    if hasattr(item, "text"):
                        return item.text.value, thread_id

        return "Sorry, I couldn't generate a response.", thread_id

    def _print_tool_trace(self, thread_id: str, run_id: str) -> None:
        """Print a readable trace of every tool/sub-agent call made during the run."""
        try:
            steps = self.client.runs.list_steps(thread_id=thread_id, run_id=run_id)
            calls: list[str] = []

            for step in steps:
                step_details = getattr(step, "step_details", None)
                for call in getattr(step_details, "tool_calls", None) or []:
                    calls.append(_describe_tool_call(call))

            if calls:
                print("🛠️  [Agent trace]")
                for line in reversed(calls):
                    print(f"   └─ {line}")
        except Exception as exc:  # tracing must never break the actual response
            logger.debug("Could not print tool trace: %s", exc)


def _parse_router_output(raw_text: str) -> dict:
    """
    Parse the Fast Router's JSON verdict, tolerating the occasional markdown code
    fence or stray text some models add around the JSON. Fails safe to
    "orchestrator" on anything unparseable rather than risk a wrong "direct" reply.
    """
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    candidate = match.group(0) if match else raw_text

    try:
        parsed = json.loads(candidate)
        route = parsed.get("route")
        if route in ("direct", "orchestrator"):
            return {"route": route, "reply": parsed.get("reply")}
    except (json.JSONDecodeError, AttributeError):
        pass

    logger.warning("Could not parse Fast Router output, routing to Orchestrator: %r", raw_text)
    return {"route": "orchestrator", "reply": None}


def _describe_tool_call(call: Any) -> str:
    call_type = getattr(call, "type", "unknown")
    if call_type == "function":
        fn = getattr(call, "function", None)
        name = getattr(fn, "name", "unknown")
        args = getattr(fn, "arguments", "{}")
        return f"function {name}({args})"
    if call_type == "connected_agent":
        details = getattr(call, "connected_agent", None)
        name = getattr(details, "name", None) or "connected_agent"
        return f"connected agent → {name}"
    if call_type == "file_search":
        return "file_search (policy PDF)"
    return str(call_type)


def get_or_create_agents() -> SmartLoanAgents:
    """Main entry point: connect to Azure AI Foundry and make sure all 3 agents exist."""
    client = get_agents_client()
    cache = _load_cache()

    policy_agent = _ensure_policy_agent(client, cache)
    fast_router = _ensure_fast_router_agent(client, cache)
    orchestrator = _ensure_orchestrator_agent(client, cache, policy_agent)

    return SmartLoanAgents(
        client=client,
        orchestrator=orchestrator,
        policy_agent=policy_agent,
        fast_router=fast_router,
    )


if __name__ == "__main__":
    # Quick manual smoke test: python agents_config.py
    logging.basicConfig(level=logging.INFO)
    agents = get_or_create_agents()

    print("\n--- Fast Router: greeting ---")
    print(agents.route("Hi there!"))

    print("\n--- Fast Router: real loan question (should route to orchestrator) ---")
    print(agents.route("Can I get a mortgage?"))

    print("\n--- Orchestrator: full flow ---")
    reply, thread_id = agents.ask(None, "Can I get a mortgage? My Telegram ID is 100001.")
    print(f"\n🤖 {reply}")
