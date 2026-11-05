"""One-off check that Bedrock's OpenAI-compatible endpoint answers.

Uses OPENAI_API_KEY / OPENAI_BASE_URL from .env (the OpenAI SDK reads them).
Superseded by app.agent.models.get_model() in M2.

Run: uv run --with openai --with python-dotenv python scripts/bedrock_openai_smoke.py
"""

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()
response = client.responses.create(
    model="openai.gpt-oss-120b",
    input=[{"role": "user", "content": "Write a one-sentence bedtime story about a unicorn."}],
)
print(response.output_text)
