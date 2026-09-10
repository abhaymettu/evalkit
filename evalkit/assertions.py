"""Assertion checks. Each returns (passed: bool, detail: str)."""
import json
import re

import jsonschema

from .model import JUDGE_SYSTEM, ModelError

TYPES = ("exact", "contains", "not_contains", "regex", "json_schema", "max_tokens", "judge")


def check(assertion, text, completion_tokens=None, model=None):
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
