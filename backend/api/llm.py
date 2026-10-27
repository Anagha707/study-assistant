import os
from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "claude").lower()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

_client = None


def _get_client():
    global _client
    if _client is None:
        if PROVIDER == "openai":
            from openai import OpenAI
            _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        else:
            import anthropic
            _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def chat(system, messages, max_tokens=700):
    """Single place where the LLM is called. Logs token usage for every call."""
    client = _get_client()
    if PROVIDER == "openai":
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}] + messages,
        )
        text = resp.choices[0].message.content
        used_in, used_out = resp.usage.prompt_tokens, resp.usage.completion_tokens
    else:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        text = resp.content[0].text
        used_in, used_out = resp.usage.input_tokens, resp.usage.output_tokens
    print(f"[TOKENS] in={used_in} out={used_out} provider={PROVIDER}")
    return text