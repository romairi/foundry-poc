from agents.base_agent import BaseAgent
from tools.weather import get_weather


class TravelAgent(BaseAgent):
    """Helps employees plan business travel with destination weather."""

    def __init__(self):
        super().__init__(
            name="Travel-Assistant",
            instructions="""You are a business travel assistant for employees.
You have 1 tool:
- get_weather: check current weather for any city

Help users decide what to pack and plan around weather at their destination.
Be concise and practical. Answer in the user's language.""",
            tools=[get_weather],
        )
