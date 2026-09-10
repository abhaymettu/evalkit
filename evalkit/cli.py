"""evalkit CLI: run, report, diff."""
import argparse
import json
import statistics
import sys
import time

from .assertions import check
from .model import MockModel, ModelError, OpenAICompatible


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def run_case(case, model):
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
    model = MockModel() if args.mock else OpenAICompatible(args.model, args.base_url)
    cases = read_jsonl(args.suite)
    results = []
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
