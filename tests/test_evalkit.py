import json

import pytest

from evalkit.assertions import check
from evalkit.cli import diff_results, main, read_jsonl, run_case, summarize
from evalkit.model import MockModel, ModelError

MOCK = MockModel()


def test_exact():
    assert check({"type": "exact", "value": "hi"}, "hi") == (True, "")
    ok, detail = check({"type": "exact", "value": "hi"}, "hi ")
    assert not ok and "expected" in detail


def test_contains_and_not_contains():
    assert check({"type": "contains", "value": "Paris"}, "Paris is nice")[0]
    assert not check({"type": "contains", "value": "Rome"}, "Paris is nice")[0]
    assert check({"type": "not_contains", "value": "Rome"}, "Paris is nice")[0]
    assert not check({"type": "not_contains", "value": "Paris"}, "Paris is nice")[0]


def test_regex():
    assert check({"type": "regex", "value": r"^\d{3}$"}, "123")[0]
    assert not check({"type": "regex", "value": r"^\d{3}$"}, "12a")[0]


def test_json_schema():
    schema = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}
    assert check({"type": "json_schema", "value": schema}, '{"n": 1}')[0]
    ok, detail = check({"type": "json_schema", "value": schema}, '{"n": "x"}')
    assert not ok and detail.startswith("schema:")
    ok, detail = check({"type": "json_schema", "value": schema}, "not json")
    assert not ok and detail.startswith("not JSON")


def test_max_tokens_uses_usage_then_falls_back():
    assert check({"type": "max_tokens", "value": 5}, "a b c", completion_tokens=3)[0]
    assert not check({"type": "max_tokens", "value": 2}, "a b c", completion_tokens=3)[0]
    ok, detail = check({"type": "max_tokens", "value": 3}, "a b c")
    assert ok and "whitespace" in detail
    assert not check({"type": "max_tokens", "value": 2}, "a b c")[0]


def test_judge_with_mock_and_without_model():
    assert check({"type": "judge", "rubric": "any"}, "this should pass", model=MOCK)[0]
    assert not check({"type": "judge", "rubric": "any"}, "nope", model=MOCK)[0]
    with pytest.raises(ModelError):
        check({"type": "judge", "rubric": "any"}, "x")


def test_unknown_type_is_recorded_as_error():
    r = run_case({"name": "u", "prompt": "MOCK: x", "assertions": [{"type": "nope"}]}, MOCK)
    assert r["pass"] is False and "unknown assertion type" in r["assertions"][0]["error"]


def test_diff_flips():
    old = [{"name": "a", "pass": False, "assertions": [{"pass": False}]},
           {"name": "b", "pass": True, "assertions": [{"pass": True}, {"pass": True}]},
           {"name": "gone", "pass": True, "assertions": []}]
    new = [{"name": "a", "pass": True, "assertions": [{"pass": True}]},
           {"name": "b", "pass": False, "assertions": [{"pass": True}, {"pass": False}]},
           {"name": "new", "pass": True, "assertions": []}]
    d = diff_results(old, new)
    assert d["fixed"] == [{"name": "a", "assertions": [0]}]
    assert d["broken"] == [{"name": "b", "assertions": [1]}]
    assert d["added"] == ["new"] and d["removed"] == ["gone"]


def test_full_mock_run_report_and_diff(tmp_path, capsys):
    out1 = tmp_path / "run1.jsonl"
    rc = main(["run", "examples/suite.jsonl", "--mock", "--out", str(out1)])
    assert rc == 1  # the example suite has one deliberate failure
    results = read_jsonl(out1)
    assert [r["pass"] for r in results] == [True, True, True, True, False]
    assert all(r["latency_ms"] >= 0 for r in results)
    s = summarize(results)
    assert s["per_type"]["exact"] == {"pass": 1, "fail": 1, "error": 0}
    assert s["per_type"]["judge"]["pass"] == 1 and s["latency_ms"]["n"] == 5

    assert main(["report", str(out1)]) == 0
    text = capsys.readouterr().out
    assert "cases: 4/5 passed" in text and "json_schema" in text and "latency ms (n=5)" in text

    # second run with the failing case fixed: diff reports it as fixed
    suite2 = tmp_path / "suite2.jsonl"
    lines = [json.loads(l) for l in open("examples/suite.jsonl")]
    lines[-1]["prompt"] = "MOCK: 42"
    suite2.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    out2 = tmp_path / "run2.jsonl"
    assert main(["run", str(suite2), "--mock", "--out", str(out2)]) == 0
    assert main(["diff", str(out1), str(out2)]) == 0
    assert "fixed   expected-failure" in capsys.readouterr().out
    assert main(["diff", str(out2), str(out1)]) == 1


def test_run_creates_missing_output_directory(tmp_path):
    out = tmp_path / "nested" / "dir" / "run.jsonl"
    main(["run", "examples/suite.jsonl", "--mock", "--out", str(out)])
    assert len(read_jsonl(out)) == 5


def test_http_200_without_choices_is_a_model_error(monkeypatch):
    import io
    import urllib.request
    from evalkit.model import OpenAICompatible

    body = json.dumps({"error": {"message": "model not found"}}).encode()
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(body))
    with pytest.raises(ModelError, match="unexpected response body"):
        OpenAICompatible("m", api_key="x").chat([{"role": "user", "content": "hi"}])
    r = run_case({"name": "c", "prompt": "hi", "assertions": [{"type": "contains", "value": "x"}]},
                 OpenAICompatible("m", api_key="x"))
    assert r["pass"] is False and "unexpected response body" in r["error"] and r["assertions"] == []
