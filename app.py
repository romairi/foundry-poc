"""Streamlit front end for the H-Bank SmartLoan multi-agent demo."""
from __future__ import annotations

import html
import json
import os
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from agents_config import (
    ORCHESTRATOR_MODEL,
    POLICY_MODEL,
    ROUTER_MODEL,
    SmartLoanAgents,
    ask_policy_agent,
    get_or_create_agents,
)
from mock_database import get_customer_financials, load_clients_database

load_dotenv()

st.set_page_config(
    page_title="H-Bank SmartLoan Agent",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      [data-testid="stAppViewContainer"] {
        background:
          radial-gradient(circle at 85% 5%, rgba(31,111,235,.10), transparent 27%),
          linear-gradient(180deg, #f8fbff 0%, #ffffff 46%);
      }
      [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #071d35 0%, #0d3154 100%);
      }
      [data-testid="stSidebar"] * { color: #f7fbff; }
      [data-testid="stSidebar"] .stSelectbox label { font-weight: 700; }
      [data-testid="stSidebar"] [data-baseweb="select"] * { color: #14283d; }
      .hero {
        padding: 1.4rem 1.6rem; border-radius: 20px; color: white;
        background: linear-gradient(120deg, #072847, #075c91 60%, #138f9d);
        box-shadow: 0 16px 35px rgba(7,40,71,.18); margin-bottom: 1.2rem;
      }
      .hero h1 { margin: 0; font-size: 2rem; }
      .hero p { margin: .45rem 0 0; opacity: .88; }
      .client-card {
        padding: 1rem; border: 1px solid rgba(255,255,255,.16);
        background: rgba(255,255,255,.08); border-radius: 16px; margin: .8rem 0 1.1rem;
      }
      .client-card h3 { margin: 0 0 .7rem; }
      .metric-row {
        display: flex; justify-content: space-between; gap: .8rem;
        padding: .28rem 0; border-bottom: 1px solid rgba(255,255,255,.09);
      }
      .metric-row:last-child { border-bottom: 0; }
      .metric-row span:first-child { opacity: .72; }
      .model-pill {
        display: flex; align-items: center; gap: .55rem; padding: .42rem .6rem;
        margin: .35rem 0; border-radius: 10px; background: rgba(255,255,255,.07);
        font-size: .84rem;
      }
      .online-dot {
        width: 9px; height: 9px; border-radius: 50%; background: #42dc91;
        box-shadow: 0 0 0 4px rgba(66,220,145,.12); flex: 0 0 auto;
      }
      .trace-box {
        background: #f2f7fc; border-left: 4px solid #1684c5; border-radius: 8px;
        padding: .65rem .8rem; color: #18344d; font-family: monospace;
      }
      .stChatMessage { border-radius: 15px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _money(value: Any) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"₪{float(value):,.0f}"


def _safe_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _profile_json(profile: dict[str, Any]) -> str:
    return json.dumps(profile, indent=2, ensure_ascii=False, default=str)


@st.cache_data(show_spinner=False)
def _clients() -> pd.DataFrame:
    return load_clients_database()


@st.cache_resource(show_spinner=False)
def _agents() -> SmartLoanAgents:
    return get_or_create_agents()


def _calculate_metrics(profile: dict[str, Any]) -> dict[str, Any]:
    income = float(profile.get("monthly_net_income") or 0)
    debts = float(profile.get("existing_debt_payments") or 0)
    requested = float(profile.get("requested_amount") or 0)
    property_value = float(profile.get("property_value") or 0)
    loan_type = str(profile.get("loan_type") or "").lower()

    dti = debts / income * 100 if income else None
    is_mortgage = "mortgage" in loan_type or "משכ" in loan_type or "ипот" in loan_type
    ltv = requested / property_value * 100 if is_mortgage and property_value else None
    return {
        "existing_obligations_dti_percent": round(dti, 2) if dti is not None else None,
        "ltv_percent": round(ltv, 2) if ltv is not None else None,
        "credit_score": profile.get("credit_score"),
        "note": (
            "DTI uses existing debt payments only because loan term and interest rate "
            "are not present in the mock database."
        ),
    }


def _policy_question(profile: dict[str, Any]) -> str:
    return (
        "Retrieve the exact H-Bank 2026 underwriting rules applicable to this application. "
        f"Loan type: {profile.get('loan_type')}; credit score: {profile.get('credit_score')}; "
        f"profession: {profile.get('profession')}; monthly net income: "
        f"{profile.get('monthly_net_income')} ILS. Include the applicable DTI limit, "
        "credit-score tier, mortgage LTV limit when relevant, and the High-Tech Exception "
        "when relevant. Cite only rules found in the policy file."
    )


def _final_prompt(
    user_message: str,
    profile: dict[str, Any],
    policy_answer: str,
    calculations: dict[str, Any],
    recent_history: list[dict[str, str]],
) -> str:
    return f"""
You are completing one step in the H-Bank SmartLoan web application.
Answer in the same language as the user's latest message.

LATEST USER MESSAGE:
{user_message}

SELECTED CLIENT RECORD (authoritative):
{_profile_json(profile)}

POLICY AGENT RAG RESULT (authoritative):
{policy_answer}

DETERMINISTIC CALCULATION INPUTS:
{_profile_json(calculations)}

RECENT CHAT CONTEXT:
{_profile_json(recent_history[-6:])}

Produce the final client-facing assessment. Verify the DTI and LTV arithmetic, compare each
metric with the retrieved policy, and state PASS/FAIL plus an overall recommendation. Clearly
say that this is a demo/preliminary assessment, not a binding credit decision. Do not call
tools: all authoritative data is already supplied above. Never invent missing policy limits,
interest rates, loan terms, or monthly payments.
""".strip()


def _render_client_card(profile: dict[str, Any]) -> None:
    fields = [
        ("Net income", _money(profile.get("monthly_net_income"))),
        ("Credit score", str(profile.get("credit_score", "N/A"))),
        ("Existing debts", _money(profile.get("existing_debt_payments"))),
        ("Loan type", str(profile.get("loan_type", "N/A"))),
        ("Requested loan", _money(profile.get("requested_amount"))),
        ("Property value", _money(profile.get("property_value"))),
        ("Down payment", _money(profile.get("down_payment"))),
    ]
    rows = "".join(
        f'<div class="metric-row"><span>{html.escape(label)}</span>'
        f"<strong>{html.escape(value)}</strong></div>"
        for label, value in fields
    )
    st.markdown(
        f"""
        <div class="client-card">
          <h3>{html.escape(str(profile.get("full_name", "Client")))}</h3>
          <div style="opacity:.72;margin-bottom:.65rem">
            {html.escape(str(profile.get("profession", "")))} · Age {profile.get("age", "N/A")}
          </div>
          {rows}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _model_status(provider: str, model: str) -> None:
    st.markdown(
        f'<div class="model-pill"><span class="online-dot"></span>'
        f"<span><b>{html.escape(provider)}</b><br>{html.escape(model)}</span></div>",
        unsafe_allow_html=True,
    )


clients_df = _clients()
if clients_df.empty:
    st.error("The client database is empty.")
    st.stop()

with st.sidebar:
    st.markdown("## 🏦 H-Bank Agent Control Panel")
    st.caption("Live underwriting demo")
    labels = {
        idx: f"{row['full_name']} — {row['profession']}"
        for idx, row in clients_df.iterrows()
    }
    selected_index = st.selectbox(
        "Select a demo client",
        options=list(labels),
        format_func=lambda idx: labels[idx],
    )
    selected_profile = {
        key: _safe_value(value) for key, value in clients_df.loc[selected_index].to_dict().items()
    }
    _render_client_card(selected_profile)
    st.markdown("#### Active model deployments")
    _model_status("OpenAI · Orchestrator", ORCHESTRATOR_MODEL)
    _model_status("Cohere · Policy RAG", POLICY_MODEL)
    _model_status("DeepSeek · Router", ROUTER_MODEL)
    st.caption("● Status is confirmed when the Azure agents initialize successfully.")

client_key = str(selected_profile.get("telegram_id", selected_index))
if st.session_state.get("selected_client_key") != client_key:
    st.session_state.selected_client_key = client_key
    st.session_state.thread_id = None
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                f"Hello {selected_profile['full_name']}! I see you are interested in a "
                f"{selected_profile['loan_type']} today. Ask me to evaluate the application "
                "or explain any part of the underwriting process."
            ),
        }
    ]

st.markdown(
    """
    <div class="hero">
      <h1>H-Bank SmartLoan Agent</h1>
      <p>Transparent multi-agent underwriting powered by Microsoft Azure AI Foundry</p>
    </div>
    """,
    unsafe_allow_html=True,
)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_message := st.chat_input("Ask about this client's loan application…"):
    st.session_state.messages.append({"role": "user", "content": user_message})
    with st.chat_message("user"):
        st.markdown(user_message)

    try:
        agents = _agents()
        with st.chat_message("assistant"):
            with st.status("Agent orchestration in progress…", expanded=True) as status:
                st.write(f"⚡ **{ROUTER_MODEL}** analyzing intent…")
                route = agents.route(user_message)
                intent = "general greeting / FAQ" if route["route"] == "direct" else "loan request"
                st.write(f"Intent detected: **{intent}**")

                if route["route"] == "direct" and route.get("reply"):
                    final_answer = route["reply"]
                    status.update(label="Handled by Fast Router", state="complete", expanded=False)
                else:
                    st.write(
                        f"🗄️ Retrieving financial data for "
                        f"**{selected_profile['full_name']}**…"
                    )
                    profile = get_customer_financials(client_key)
                    st.json(profile, expanded=False)

                    st.write(f"📚 **{POLICY_MODEL}** searching underwriting policy…")
                    policy_answer = ask_policy_agent(_policy_question(profile))
                    st.markdown(
                        f'<div class="trace-box">{html.escape(policy_answer)}</div>',
                        unsafe_allow_html=True,
                    )

                    calculations = _calculate_metrics(profile)
                    st.write(f"🧮 **{ORCHESTRATOR_MODEL}** running DTI & LTV calculations…")
                    dti_text = (
                        f"{calculations['existing_obligations_dti_percent']:.2f}%"
                        if calculations["existing_obligations_dti_percent"] is not None
                        else "N/A"
                    )
                    ltv_text = (
                        f"{calculations['ltv_percent']:.2f}%"
                        if calculations["ltv_percent"] is not None
                        else "N/A"
                    )
                    st.code(f"DTI = existing debts / net income = {dti_text}\nLTV = loan / property value = {ltv_text}")

                    final_answer, thread_id = agents.ask(
                        st.session_state.thread_id,
                        _final_prompt(
                            user_message,
                            profile,
                            policy_answer,
                            calculations,
                            st.session_state.messages,
                        ),
                    )
                    st.session_state.thread_id = thread_id
                    status.update(
                        label="Multi-agent assessment complete",
                        state="complete",
                        expanded=False,
                    )

            st.markdown(final_answer)
        st.session_state.messages.append({"role": "assistant", "content": final_answer})
    except Exception as exc:
        error_message = (
            "I couldn't complete the assessment. Confirm that `az login` is active, the three "
            "model deployments exist, and the Azure project configuration in `.env` is correct."
        )
        st.error(error_message)
        with st.expander("Technical details"):
            st.code(f"{type(exc).__name__}: {exc}")
        st.session_state.messages.append({"role": "assistant", "content": error_message})
