"""
mock_database.py

Reads the mock client database (`mock_clients_database.xlsx`) and exposes
`get_customer_financials`, the local Tool used by the Orchestrator Agent to
fetch a customer's financial profile by their Telegram ID.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

DATABASE_PATH = Path(__file__).parent / "mock_clients_database.xlsx"

# Maps the human-readable Excel headers (with currency symbols) to clean,
# JSON/tool-friendly snake_case keys.
_COLUMN_MAP = {
    "Telegram ID": "telegram_id",
    "Full Name": "full_name",
    "Age": "age",
    "Profession": "profession",
    "Monthly Net Income (₪)": "monthly_net_income",
    "Existing Debt Payments (₪)": "existing_debt_payments",
    "Credit Score": "credit_score",
    "Loan Type": "loan_type",
    "Requested Amount (₪)": "requested_amount",
    "Property Value (₪)": "property_value",
    "Down Payment (₪)": "down_payment",
}

_dataframe: Optional[pd.DataFrame] = None


def _load_dataframe(force_reload: bool = False) -> pd.DataFrame:
    """Load (and cache) the client database as a DataFrame with normalized columns."""
    global _dataframe
    if _dataframe is None or force_reload:
        if not DATABASE_PATH.exists():
            raise FileNotFoundError(
                f"Client database not found at '{DATABASE_PATH}'. "
                "Make sure 'mock_clients_database.xlsx' is in the project root."
            )
        raw = pd.read_excel(DATABASE_PATH)
        raw = raw.rename(columns=_COLUMN_MAP)
        raw["telegram_id"] = raw["telegram_id"].astype(str)
        _dataframe = raw
        logger.info("Loaded %d client records from %s", len(raw), DATABASE_PATH.name)
    return _dataframe


def get_customer_financials(telegram_id: str) -> dict:
    """
    Look up a customer's financial profile by their Telegram ID.

    Acts as a local Tool for the Orchestrator Agent: given the Telegram ID of
    the person writing to the bot, it returns their financial profile from the
    mock bank database so the agents can evaluate a loan application.

    :param telegram_id: The Telegram user ID of the customer, as a string.
    :return: A dict describing the customer's financial profile
        (status="found"), or a dict with status="unknown_customer" if no
        matching record exists, so the bot can ask the user for their
        details manually instead.
    """
    df = _load_dataframe()
    match = df[df["telegram_id"] == str(telegram_id)]

    if match.empty:
        return {
            "status": "unknown_customer",
            "telegram_id": str(telegram_id),
            "message": (
                "No record found for this Telegram ID in the client database. "
                "Ask the user to provide the following details manually: age, "
                "profession, monthly net income, existing debt payments, credit "
                "score, loan type, requested amount, property value and down payment."
            ),
        }

    row = match.iloc[0]
    return {
        "status": "found",
        "telegram_id": row["telegram_id"],
        "full_name": row["full_name"],
        "age": int(row["age"]),
        "profession": row["profession"],
        "monthly_net_income": int(row["monthly_net_income"]),
        "existing_debt_payments": int(row["existing_debt_payments"]),
        "credit_score": int(row["credit_score"]),
        "loan_type": row["loan_type"],
        "requested_amount": int(row["requested_amount"]),
        "property_value": int(row["property_value"]),
        "down_payment": int(row["down_payment"]),
        "currency": "ILS (₪)",
    }


if __name__ == "__main__":
    # Quick manual smoke test: python mock_database.py
    logging.basicConfig(level=logging.INFO)
    df = _load_dataframe()
    sample_id = df.iloc[0]["telegram_id"]
    print(get_customer_financials(sample_id))
    print(get_customer_financials("no-such-id"))
