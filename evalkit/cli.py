"""evalkit CLI: ``run``, ``report``, ``diff``.

``run`` executes a JSONL suite and writes one JSON result per line.
``report`` summarizes a results file. ``diff`` compares two results files
case by case and lists what flipped.
"""
import argparse
import json
import os
import statistics
import sys
import time

from .assertions import check
from .model import MockModel, ModelError, OpenAICompatible


def read_jsonl(path):
    """Read a JSONL file into a list of parsed objects.

    Args:
        path: File path. Blank lines are skipped.

    Returns:
        List of decoded JSON values, one per non-blank line.

    Raises:
        OSError: The file cannot be opened.
        json.JSONDecodeError: A non-blank line is not valid JSON.
    """
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def run_case(case, model):
    """Send one case's prompt to the model and evaluate its assertions.

    Args:
        case: Suite object with ``name``, ``prompt``, optional ``system``,
            and optional ``assertions`` (a list of assertion dicts).
        model: A client with a ``chat`` method and a ``model`` attribute.

    Returns:
        A result dict with ``name``, ``prompt``, ``model``, ``ran_at``,
        ``assertions``, and ``pass``. On a successful model call it also has
        ``response``, ``latency_ms`` (rounded to 2 decimals), and
        ``completion_tokens``. Each assertion entry has ``type`` and ``pass``
        plus either ``detail`` or ``error``. A case with no assertions
        passes.

        If the model call raises ``ModelError``, the result has ``error`` set
        to the message, ``response`` and ``latency_ms`` set to None, an empty
        ``assertions`` list, and ``pass`` False.

    Raises:
        KeyError: ``case`` lacks ``name`` or ``prompt``.
    """
    messages = []
    if case.get("system"):
        messages.append({"role": "system", "content": case["system"]})
    messages.append({"role": "user", "content": case["prompt"]})
    result = {"name": case["name"], "prompt": case["prompt"], "model": model.model,
              "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "assertions": []}
    try:
        reply = model.chat(messages)
    except ModelError as e:
        result.update({"error": str(e), "response": None, "latency_ms": None, "pass": False})
        return result
    result["response"] = reply["text"]
    result["latency_ms"] = round(reply["latency_ms"], 2)
    result["completion_tokens"] = reply["completion_tokens"]
    for a in case.get("assertions", []):
        entry = {"type": a.get("type")}
        try:
            entry["pass"], entry["detail"] = check(a, reply["text"], reply["completion_tokens"], model)
        except (ModelError, ValueError, KeyError) as e:
            entry.update({"pass": False, "error": str(e)})
        result["assertions"].append(entry)
    result["pass"] = all(a["pass"] for a in result["assertions"])
    return result


def cmd_run(args):
    """Handle ``evalkit run``: run every case in order and stream results to ``--out``.

    Creates the parent directory of ``--out`` if it does not exist. Prints
    one ``PASS`` or ``FAIL`` line per case as it finishes, then a summary line.

    Args:
        args: Parsed namespace with ``suite``, ``out``, ``mock``, ``model``,
            and ``base_url``.

    Returns:
        0 if every case passed, else 1.
    """
    model = MockModel() if args.mock else OpenAICompatible(args.model, args.base_url)
    cases = read_jsonl(args.suite)
    results = []
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as out:
        for case in cases:
            r = run_case(case, model)
            results.append(r)
            out.write(json.dumps(r) + "\n")
            print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['name']}" + (f"  ({r['error']})" if r.get("error") else ""))
    passed = sum(r["pass"] for r in results)
    print(f"\n{passed}/{len(results)} cases passed. Results: {args.out}")
    return 0 if passed == len(results) else 1


def summarize(results):
    """Aggregate a list of result dicts.

    Args:
        results: Result dicts as written by ``run``.

    Returns:
        Dict with ``cases`` (count), ``cases_passed``, ``errors`` (cases whose
        model call failed), ``per_type`` (assertion type to
        ``{"pass", "fail", "error"}`` counts, where ``error`` means the
        assertion entry has an ``error`` key), and ``latency_ms``. The latency
        block is None when no case has a measured latency; otherwise it holds
        ``n``, ``min``, ``median``, ``p95``, and ``max``. ``p95`` is the value
        at sorted index ``round(0.95 * (n - 1))``, not an interpolation.
    """
    per_type = {}
    for r in results:
        for a in r["assertions"]:
            bucket = per_type.setdefault(a["type"], {"pass": 0, "fail": 0, "error": 0})
            bucket["error" if "error" in a else "pass" if a["pass"] else "fail"] += 1
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms") is not None]
    lat = None
    if latencies:
        s = sorted(latencies)
        lat = {"n": len(s), "min": s[0], "median": statistics.median(s),
               "p95": s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))], "max": s[-1]}
    return {"cases": len(results), "cases_passed": sum(r["pass"] for r in results),
            "errors": sum(1 for r in results if r.get("error")),
            "per_type": per_type, "latency_ms": lat}


def cmd_report(args):
    """Handle ``evalkit report``: print the summary of one results file.

    Args:
        args: Parsed namespace with ``results``.

    Returns:
        0 always. The report is informational.
    """
    s = summarize(read_jsonl(args.results))
    print(f"cases: {s['cases_passed']}/{s['cases']} passed, {s['errors']} model errors\n")
    print(f"{'assertion':<14}{'pass':>6}{'fail':>6}{'error':>7}")
    for t, c in s["per_type"].items():
        print(f"{t:<14}{c['pass']:>6}{c['fail']:>6}{c['error']:>7}")
    lat = s["latency_ms"]
    if lat:
        print(f"\nlatency ms (n={lat['n']}): min {lat['min']:.0f}  median {lat['median']:.0f}  p95 {lat['p95']:.0f}  max {lat['max']:.0f}")
    else:
        print("\nlatency: no measured timings")
    return 0


def diff_results(old, new):
    """Compare two result lists by case name.

    Args:
        old: Result dicts from the earlier run.
        new: Result dicts from the later run.

    Returns:
        Dict with four sorted lists. ``fixed`` and ``broken`` hold
        ``{"name", "assertions"}`` entries for cases whose case-level ``pass``
        flipped from False to True or True to False. ``assertions`` lists the
        positional indexes whose ``pass`` differs between the two runs, pairing
        entries with ``zip``, so extra assertions in the longer list are not
        compared. ``added`` and ``removed`` hold names present in only one
        run. Cases whose case-level result did not change are not reported,
        even if individual assertions flipped.
    """
    a = {r["name"]: r for r in old}
    b = {r["name"]: r for r in new}
    out = {"fixed": [], "broken": [], "added": [], "removed": []}
    for name in a.keys() - b.keys():
        out["removed"].append(name)
    for name in b.keys() - a.keys():
        out["added"].append(name)
    for name in a.keys() & b.keys():
        was, now = a[name]["pass"], b[name]["pass"]
        flipped = [i for i, (x, y) in enumerate(zip(a[name]["assertions"], b[name]["assertions"])) if x["pass"] != y["pass"]]
        if not was and now:
            out["fixed"].append({"name": name, "assertions": flipped})
        elif was and not now:
            out["broken"].append({"name": name, "assertions": flipped})
    for k in out:
        out[k].sort(key=lambda x: x if isinstance(x, str) else x["name"])
    return out


def cmd_diff(args):
    """Handle ``evalkit diff``: print what flipped between two results files.

    Args:
        args: Parsed namespace with ``old`` and ``new``.

    Returns:
        1 if any case broke, else 0. Fixed, added, and removed cases do not
        affect the exit code.
    """
    d = diff_results(read_jsonl(args.old), read_jsonl(args.new))
    for k in ("fixed", "broken"):
        for item in d[k]:
            print(f"{k:<8}{item['name']}  (assertion index: {item['assertions']})")
    for k in ("added", "removed"):
        for name in d[k]:
            print(f"{k:<8}{name}")
    if not any(d.values()):
        print("no flips")
    print(f"\nfixed {len(d['fixed'])}  broken {len(d['broken'])}  added {len(d['added'])}  removed {len(d['removed'])}")
    return 1 if d["broken"] else 0


def main(argv=None):
    """Parse arguments and dispatch to a subcommand.

    Args:
        argv: Argument list without the program name. Defaults to
            ``sys.argv[1:]``.

    Returns:
        The subcommand's exit code. Exits with status 2 on a usage error.
    """
    p = argparse.ArgumentParser(prog="evalkit", description="Minimal LLM output assertion runner.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a suite and write results JSONL")
    r.add_argument("suite")
    r.add_argument("--model", default="gpt-4o-mini")
    r.add_argument("--base-url", default="https://api.openai.com/v1")
    r.add_argument("--out", required=True)
    r.add_argument("--mock", action="store_true", help="use the deterministic fake model, no key needed")
    r.set_defaults(fn=cmd_run)
    rp = sub.add_parser("report", help="summarize a results file")
    rp.add_argument("results")
    rp.set_defaults(fn=cmd_report)
    d = sub.add_parser("diff", help="show which cases flipped between two results files")
    d.add_argument("old")
    d.add_argument("new")
    d.set_defaults(fn=cmd_diff)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
