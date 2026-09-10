"""Chat model clients: an OpenAI-compatible HTTP client and a deterministic mock.

Both clients expose the same ``chat(messages, model=None)`` method and return a
dict with keys ``text``, ``latency_ms``, and ``completion_tokens``. The runner
and the ``judge`` assertion depend only on that shape.
"""
import json
import os
import time
import urllib.error
import urllib.request

JUDGE_SYSTEM = "You are a strict grader. Reply with exactly one word: PASS or FAIL."
MOCK_PREFIX = "MOCK:"


class ModelError(Exception):
    """A model call failed or returned something the client could not use.

    Raised for transport errors, non-2xx HTTP status, a 2xx body that is not
    a chat completion, and a ``judge`` assertion run with no model. The runner
    catches this per case and records it in the result's ``error`` field
    instead of aborting the run.
    """


class OpenAICompatible:
    """HTTP client for any server that speaks ``POST {base_url}/chat/completions``.

    Args:
        model: Default model name sent in the request body.
        base_url: API root. A trailing slash is stripped.
        api_key: Bearer token. Falls back to the ``OPENAI_API_KEY`` environment
            variable. If both are empty no Authorization header is sent, which
            suits local servers such as Ollama or vLLM.
        timeout: Socket timeout in seconds for each request.
    """

    def __init__(self, model, base_url="https://api.openai.com/v1", api_key=None, timeout=60):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.timeout = timeout

    def chat(self, messages, model=None):
        """Send one chat completion request and return the first choice.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            model: Model name for this call. Defaults to ``self.model``.

        Returns:
            Dict with ``text`` (the assistant content, empty string if null),
            ``latency_ms`` (wall time around the HTTP call as a float), and
            ``completion_tokens`` (from ``usage`` in the response, or None if
            the server did not report usage).

        Raises:
            ModelError: On HTTP error status, connection failure, timeout, a
                body that is not JSON, or a JSON body without the expected
                ``choices[0].message.content`` path.
        """
        body = json.dumps({"model": model or self.model, "messages": messages}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers=headers)
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise ModelError(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise ModelError(str(e)) from e
        latency_ms = (time.perf_counter() - start) * 1000
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ModelError(f"unexpected response body: {raw[:300].decode(errors='replace')}") from e
        usage = data.get("usage") or {}
        tokens = usage.get("completion_tokens")
        return {"text": text, "latency_ms": latency_ms, "completion_tokens": tokens}


class MockModel:
    """Deterministic fake model so the whole pipeline runs offline.

    Behavior, in order of precedence:

    1. If the system message equals ``JUDGE_SYSTEM`` the call is a judge call.
       The reply is ``PASS`` when the text after ``Response:\\n`` in the user
       message contains the word ``pass`` (case-insensitive), else ``FAIL``.
    2. If the last user message starts with ``MOCK:`` the reply is the rest of
       that message with the prefix and leading whitespace removed.
    3. Otherwise the reply is ``mock reply for: <user message>``.

    ``completion_tokens`` is the whitespace word count of the reply.
    """

    model = "mock"

    def chat(self, messages, model=None):
        """Return a canned reply following the rules in the class docstring.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            model: Ignored. Present so the signature matches ``OpenAICompatible``.

        Returns:
            Dict with ``text``, ``latency_ms``, and ``completion_tokens``.
        """
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
