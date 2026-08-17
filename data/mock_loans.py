"""מאגר הלוואות מדומה בעברית (הקשר ישראלי)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).with_name("mock_data.json")

with _DATA_PATH.open(encoding="utf-8") as fh:
    LOANS: list[dict[str, Any]] = json.load(fh)


def get_all_loans() -> list[dict[str, Any]]:
    return LOANS


def get_loan_by_client_id(client_id: str) -> dict[str, Any] | None:
    needle = (client_id or "").strip().upper()
    for row in LOANS:
        if str(row.get("client_id", "")).upper() == needle:
            return row
    return None


def search_loans_by_name(name: str) -> list[dict[str, Any]]:
    needle = (name or "").strip()
    if not needle:
        return []
    return [row for row in LOANS if needle in str(row.get("client_name", ""))]


def evaluate_loan(record: dict[str, Any]) -> dict[str, Any]:
    """
    כללי עסק בעברית:
    - דירוג אשראי מתחת ל-600 → נדחה
    - סכום מבוקש מעל 40% מההכנסה השנתית → בבדיקה / סיכון גבוה
    - אחרת → אושר אם הדירוג ≥ 700, אחרת בבדיקה
    """
    income = float(record.get("monthly_income") or 0)
    amount = float(record.get("requested_amount") or 0)
    score = int(record.get("credit_score") or 0)
    annual = income * 12
    ratio = (amount / annual) if annual else 1.0

    if score < 600:
        recommendation = "נדחה"
        reason = "דירוג אשראי נמוך מ-600. לפי מדיניות הבנק לא ניתן לאשר בשלב זה."
    elif ratio > 0.40:
        recommendation = "בבדיקה"
        reason = "סכום ההלוואה עולה על 40% מההכנסה השנתית. נדרש אישור מנהל וערבים."
    elif score >= 700 and ratio <= 0.25:
        recommendation = "אושר"
        reason = "דירוג אשראי תקין ויחס החזר סביר. ניתן להמשיך לתהליך חתימה."
    else:
        recommendation = "בבדיקה"
        reason = "נתונים גבוליים. מומלץ בדיקת מסמכים נוספת והכנסה פנויה."

    return {
        "client_id": record.get("client_id"),
        "client_name": record.get("client_name"),
        "סטטוס_נוכחי": record.get("status"),
        "המלצת_מערכת": recommendation,
        "נימוק": reason,
        "יחס_הלוואה_להכנסה_שנתית": round(ratio, 3),
        "סכום_מבוקש_₪": amount,
        "הכנסה_חודשית_₪": income,
        "דירוג_אשראי": score,
        "מטרה": record.get("purpose"),
    }
