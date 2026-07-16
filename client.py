from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionTool, ToolSet
from azure.identity import DefaultAzureCredential

from config import ENDPOINT
from tools.calculator import calculate
from tools.search import search_corporate
from tools.weather import get_weather

_client: AgentsClient | None = None
_toolset: ToolSet | None = None


def get_agents_client() -> AgentsClient | None:
    global _client
    if _client is None:
        _client = AgentsClient(
            endpoint=ENDPOINT,
            credential=DefaultAzureCredential(),
        )
    return _client


def get_toolset() -> ToolSet | None:
    """Shared toolset with all registered functions for auto function calls."""
    global _toolset
    if _toolset is None:
        functions = FunctionTool(functions={get_weather, calculate, search_corporate})
        _toolset = ToolSet()
        _toolset.add(functions)
        get_agents_client().enable_auto_function_calls(_toolset)
    return _toolset
