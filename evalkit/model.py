"""Chat model clients: an OpenAI-compatible HTTP client and a deterministic mock."""
import json
import os
import time
import urllib.error
import urllib.request

JUDGE_SYSTEM = "You are a strict grader. Reply with exactly one word: PASS or FAIL."
MOCK_PREFIX = "MOCK:"


class ModelError(Exception):
    pass


class OpenAICompatible:
    """Calls POST {base_url}/chat/completions. Key comes from OPENAI_API_KEY."""

    def __init__(self, model, base_url="https://api.openai.com/v1", api_key=None, timeout=60):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.timeout = timeout

    def chat(self, messages, model=None):
        body = json.dumps({"model": model or self.model, "messages": messages}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers=headers)
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise ModelError(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise ModelError(str(e)) from e
        latency_ms = (time.perf_counter() - start) * 1000
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        tokens = usage.get("completion_tokens")
        return {"text": text, "latency_ms": latency_ms, "completion_tokens": tokens}


class MockModel:
    """Deterministic fake. A user message starting with 'MOCK:' is echoed back
    without the prefix; anything else gets a fixed reply. Judge calls return
    PASS when the judged response contains the word 'pass' (case-insensitive)."""

    model = "mock"

    def chat(self, messages, model=None):
        start = time.perf_counter()
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if system == JUDGE_SYSTEM:
            judged = user.split("Response:\n", 1)[-1]
            text = "PASS" if "pass" in judged.lower() else "FAIL"
        elif user.startswith(MOCK_PREFIX):
            text = user[len(MOCK_PREFIX):].lstrip()
        else:
            text = f"mock reply for: {user}"
        return {"text": text, "latency_ms": (time.perf_counter() - start) * 1000,
                "completion_tokens": len(text.split())}
