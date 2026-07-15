from agents.base_agent import BaseAgent
from tools.calculator import calculate
from tools.search import search_corporate


class CorporateAgent(BaseAgent):
    """Handles company policies, schedules, contacts, and expense math."""

    def __init__(self):
        super().__init__(
            name="Corporate-Assistant",
            instructions="""You are a helpful corporate assistant for employees.
You have 2 tools:
- search_corporate: find company info (policies, schedules, contacts, expenses)
- calculate: do math calculations (tips, conversions, percentages)

Use the right tool based on the user's question. Be concise. Answer in the user's language.""",
            tools=[search_corporate, calculate],
        )
