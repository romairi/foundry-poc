"""בדיקה מקומית: ארבע שאלות בעברית ברצף."""

from agent import run_external_agent

PROMPTS = [
    ("1 פשוט", "שלום, מה הסטטוס של הלקוח דוד כהן, מספר IL-1001?"),
    ("2 אחזור", "מה הסטטוס של ההלוואה של מיכל לוי?"),
    ("3 הערכה", "האם לאשר ליוסי מזרחי את הסכום שביקש? נמק לפי כללי הבנק."),
    ("4 לא במאגר", "מה הסטטוס של לקוח IL-9999?"),
]


if __name__ == "__main__":
    for label, prompt in PROMPTS:
        print("=" * 72)
        print(f"[{label}]\n{prompt}\n")
        print(run_external_agent(prompt))
        print()
