"""Assertion checks. ``check`` dispatches on ``assertion["type"]``.

Every check returns ``(passed, detail)``. ``detail`` is an empty string on
pass for most types, and a short human-readable reason on failure. The
``max_tokens`` check always fills ``detail`` so the count and its source are
recorded even when it passes. See docs/assertions.md for the exact messages.
"""
import json
import re

import jsonschema

from .model import JUDGE_SYSTEM, ModelError

TYPES = ("exact", "contains", "not_contains", "regex", "json_schema", "max_tokens", "judge")


def check(assertion, text, completion_tokens=None, model=None):
    """Evaluate one assertion against a model reply.

    Args:
        assertion: Dict with a ``type`` key and the fields that type needs.
            ``exact``, ``contains``, ``not_contains``, ``regex``, ``json_schema``
            and ``max_tokens`` read ``value``. ``judge`` reads ``rubric`` and
            an optional ``model`` override.
        text: The model reply to check.
        completion_tokens: Token count reported by the API, or None. Only
            ``max_tokens`` uses it. When None, ``max_tokens`` falls back to a
            whitespace word count and says so in ``detail``.
        model: A client with a ``chat`` method. Only ``judge`` uses it.

    Returns:
        ``(passed, detail)``. ``passed`` is a bool. ``detail`` is a string.

    Raises:
        ValueError: ``type`` is not one of ``TYPES``.
        KeyError: A required field for the type is missing.
        ModelError: ``judge`` was called with ``model=None``, or the judge
            call itself failed.
        re.error: ``regex`` has an invalid pattern.
        jsonschema.SchemaError: ``json_schema`` has an invalid schema.
    """
    kind = assertion.get("type")
    if kind == "exact":
        want = assertion["value"]
        return text == want, "" if text == want else f"expected {want!r}, got {text[:200]!r}"
    if kind == "contains":
        ok = assertion["value"] in text
        return ok, "" if ok else f"{assertion['value']!r} not found"
    if kind == "not_contains":
        ok = assertion["value"] not in text
        return ok, "" if ok else f"{assertion['value']!r} found"
    if kind == "regex":
        ok = re.search(assertion["value"], text, re.MULTILINE) is not None
        return ok, "" if ok else f"no match for /{assertion['value']}/"
    if kind == "json_schema":
        try:
            jsonschema.validate(json.loads(text), assertion["value"])
            return True, ""
        except json.JSONDecodeError as e:
            return False, f"not JSON: {e}"
        except jsonschema.ValidationError as e:
            return False, f"schema: {e.message}"
    if kind == "max_tokens":
        limit = int(assertion["value"])
        if completion_tokens is None:
            completion_tokens = len(text.split())
            source = "whitespace count, no usage in response"
        else:
            source = "completion_tokens from response"
        ok = completion_tokens <= limit
        return ok, f"{completion_tokens} tokens ({source})" + ("" if ok else f", limit {limit}")
    if kind == "judge":
        if model is None:
            raise ModelError("judge assertion needs a model")
        user = f"Rubric:\n{assertion['rubric']}\n\nResponse:\n{text}"
        reply = model.chat([{"role": "system", "content": JUDGE_SYSTEM},
                            {"role": "user", "content": user}], model=assertion.get("model"))
        verdict = reply["text"].strip().upper()
        return verdict.startswith("PASS"), f"judge said {reply['text'].strip()[:200]!r}"
    raise ValueError(f"unknown assertion type {kind!r}; known: {', '.join(TYPES)}")
