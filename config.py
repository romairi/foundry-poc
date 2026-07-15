import os

from dotenv import load_dotenv

load_dotenv()

ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
MODEL_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5.4-mini")
