"""
Base agent class — shared logic for creating and running agents.
All agents inherit from this.
"""
from typing import Callable, List

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionTool, ToolSet

from azure.ai.agents.models import AgentThreadCreationOptions, ThreadMessageOptions

from client import get_agents_client, get_toolset
from config import MODEL_NAME


class BaseAgent:
    """
    Base class for all agents. Handles:
    - Agent creation with tools
    - Thread/conversation management
    - Automatic tool call execution
    - Cleanup
    """

    def __init__(self, name: str, instructions: str, tools: List[Callable] = None):
        """
        Args:
            name: Agent display name
            instructions: System prompt / instructions for the agent
            tools: List of actual Python function objects (callables)
        """
        self.name = name
        self.instructions = instructions
        self.tools = tools or []
        self.client: AgentsClient = get_agents_client()
        self.agent = None
        self.thread = None
        self._agent_toolset = ToolSet()

        if self.tools:
            functions = FunctionTool(functions=self.tools)
            self._agent_toolset.add(functions)

    def create(self):
        """Create the agent on the server with its tools."""
        get_toolset()

        self.agent = self.client.create_agent(
            model=MODEL_NAME,
            name=self.name,
            instructions=self.instructions,
            toolset=self._agent_toolset if self.tools else None,
        )

        print(f"[{self.name}] Agent created: {self.agent.id}")
        return self

    def start_conversation(self):
        """Create a new thread (conversation)."""
        self.thread = self.client.threads.create()
        print(f"[{self.name}] Thread created: {self.thread.id}")
        return self

    def ask(self, content: str) -> str:
        """
        Send a one-shot question and return the agent's response.
        Handles the tool-call loop automatically.
        """
        thread_options = AgentThreadCreationOptions(
            messages=[ThreadMessageOptions(role="user", content=content)]
        )

        run = self.client.create_thread_and_process_run(
            agent_id=self.agent.id,
            toolset=get_toolset(),
            thread=thread_options,
        )

        if run.status == "failed":
            print(f"[{self.name}] Run failed: {run.last_error}")
            return f"Error: {run.last_error}"

        self._print_tool_executions(run.thread_id, run.id)

        messages = self.client.messages.list(thread_id=run.thread_id)
        for msg in messages:
            if msg.role == "assistant":
                for item in msg.content:
                    if hasattr(item, "text"):
                        return item.text.value

        return "No response generated."

    def _print_tool_executions(self, thread_id: str, run_id: str):
        try:
            steps = self.client.runs.list_steps(thread_id=thread_id, run_id=run_id)
            tool_calls = []

            for step in steps:
                if hasattr(step, "step_details") and step.step_details:
                    calls = getattr(step.step_details, "tool_calls", None)
                    if calls:
                        for call in calls:
                            func_info = getattr(call, "function", None)
                            if func_info:
                                name = getattr(func_info, "name", "unknown")
                                args = getattr(func_info, "arguments", "{}")
                                tool_calls.append(f"{name}({args})")

            if tool_calls:
                print("🛠️  [System Call Logs]")
                for call_signature in reversed(tool_calls):
                    print(f"   └─ Executed: {call_signature}")
        except Exception:
            pass

    def cleanup(self):
        """Delete the agent from the server (free resources)."""
        if self.agent:
            self.client.delete_agent(self.agent.id)
            print(f"[{self.name}] Agent deleted.")