import os
import sys
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

# Load environment variables from a .env file
load_dotenv()

# Configuration Constants (Reads from .env, falls back to defaults if not found)
AZURE_AI_ENDPOINT = os.getenv(
    "AZURE_AI_PROJECT_ENDPOINT",
    "https://roman-foundry-poc.services.ai.azure.com/api/projects/roman-agent-evaluation"
)
AGENT_NAME = os.getenv("AZURE_AGENT_NAME", "Roman-Corporate-Bot")
AGENT_VERSION = os.getenv("AZURE_AGENT_VERSION", "2")

def run_agent_official_way():
    # Validate configuration before executing
    if not AZURE_AI_ENDPOINT or not AGENT_NAME:
        print("Error: Missing configuration parameters. Please check your constants or .env file.")
        sys.exit(1)

    print("Authenticating with Azure AI Foundry...")
    try:
        project_client = AIProjectClient(
            endpoint=AZURE_AI_ENDPOINT,
            credential=DefaultAzureCredential(),
        )

        print("Initializing OpenAI-compatible runtime client...")
        openai_client = project_client.get_openai_client()

        user_query = "What is the corporate shuttle schedule for Route 101 tomorrow?"
        print(f"\nUser: {user_query}")

        print("Sending request via Responses API...")
        # Fix: Passing user_query directly as a string resolves the PyCharm type warning,
        # as the SDK expects a primitive 'str' or specific typed objects rather than a raw list of dicts.
        response = openai_client.responses.create(
            input=user_query,
            extra_body={
                "agent_reference": {
                    "name": AGENT_NAME,
                    "version": AGENT_VERSION,
                    "type": "agent_reference"
                }
            },
        )

        print(f"\nAgent Response:\n{response.output_text}")

    except Exception as e:
        print(f"\nAn error occurred during execution: {e}")

if __name__ == "__main__":
    run_agent_official_way()