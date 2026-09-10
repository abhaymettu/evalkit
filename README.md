# evalkit

A minimal assertion runner for LLM outputs.

You write a suite file. Each line is a prompt plus a list of assertions. evalkit sends
the prompt to any OpenAI-compatible chat endpoint, checks the reply against the
assertions, and writes one result line per case. You can then print a summary of a run
or compare two runs to see which cases flipped.

## What it does

- Runs a JSONL suite against a chat completions endpoint, one case at a time.
- Checks seven assertion types: `exact`, `contains`, `not_contains`, `regex`,
  `json_schema`, `max_tokens`, `judge`. See [docs/assertions.md](docs/assertions.md).
- Records the reply, per-assertion pass or fail with a reason, and the measured request
  latency.
- Reports pass, fail, and error counts per assertion type, plus latency stats.
- Diffs two result files and lists what got fixed, what broke, what was added or removed.
- Has a `--mock` mode with a deterministic fake model so the whole pipeline runs offline.

## What it does not do

- It is not a benchmark. It has no built-in datasets and no scores to compare across
  models. It tells you whether your own cases pass.
- No leaderboards, no dashboards, no history beyond the result files you keep.
- No retries, no concurrency, no rate limiting. Cases run one at a time.
- No token counting of its own. `max_tokens` uses the `completion_tokens` value the API
  returns. If the API omits usage, it falls back to a whitespace word count and says so
  in the detail.
- `judge` assertions are only as good as the judge prompt and the judge model. A PASS
  from the judge is the judge's opinion, not ground truth. The judge is not calibrated,
  not validated against human labels, and can disagree with itself across runs.
- The six deterministic assertion types need no model key. The `judge` type makes a
  second model call and needs a key unless you are in mock mode.

## Install

Python 3.11 or newer.

```
git clone <this repo> evalkit
cd evalkit
./setup.sh
```

`setup.sh` creates `.venv`, installs the pinned dependencies from `requirements.txt`,
installs evalkit in editable mode, runs the tests, and prints the usage line. It is safe
to run again.

Dependencies: `jsonschema` for the `json_schema` assertion, `pytest` for the tests.
HTTP uses the standard library.

## Usage

Run a suite against a real endpoint. The key is read from `OPENAI_API_KEY`.

```
export OPENAI_API_KEY=...
.venv/bin/evalkit run suite.jsonl --model gpt-4o-mini --base-url https://api.openai.com/v1 --out results/run1.jsonl
```

`--base-url` accepts any server that speaks the `/chat/completions` protocol, for example
a local Ollama or vLLM server. If `OPENAI_API_KEY` is unset no Authorization header is
sent. The parent directory of `--out` is created if it does not exist.

Exit codes: `run` returns 1 if any case failed, `diff` returns 1 if any case broke,
`report` always returns 0.

### A real run in mock mode

Everything below is copied from one terminal session on 2026-09-10, unedited, using the
example suite and the fake model. The example suite includes one deliberate failure so
the report and diff have something to show.

Run the suite:

```
$ evalkit run examples/suite.jsonl --mock --out results/run1.jsonl
PASS  greeting-exact
PASS  contains-and-not
PASS  json-shape
PASS  judged
FAIL  expected-failure

4/5 cases passed. Results: results/run1.jsonl
```

Exit code 1, because one case failed. Summarize it:

```
$ evalkit report results/run1.jsonl
cases: 4/5 passed, 0 model errors

assertion       pass  fail  error
exact              1     1      0
max_tokens         1     0      0
contains           1     0      0
not_contains       1     0      0
regex              1     0      0
json_schema        1     0      0
judge              1     0      0

latency ms (n=5): min 0  median 0  p95 0  max 0
```

Latency is measured around each model call. The mock model does no I/O, so it rounds to
zero. Against a real endpoint these are wall-clock milliseconds.

The failing case's result line, so you can see what gets stored:

```
{"name": "expected-failure", "prompt": "MOCK: forty-two", "model": "mock", "ran_at": "2026-09-10T11:09:26-0500", "assertions": [{"type": "exact", "pass": false, "detail": "expected '42', got 'forty-two'"}], "response": "forty-two", "latency_ms": 0.0, "completion_tokens": 1, "pass": false}
```

Now change that case's prompt to `MOCK: 42`, run again to `results/run2.jsonl`, and diff:

```
$ evalkit diff results/run1.jsonl results/run2.jsonl
fixed   expected-failure  (assertion index: [0])

fixed 1  broken 0  added 0  removed 0
```

Exit code 0. The same diff with the arguments reversed reports the case as broken and
exits 1:

```
$ evalkit diff results/run2.jsonl results/run1.jsonl
broken  expected-failure  (assertion index: [0])

fixed 0  broken 1  added 0  removed 0
```

When the model call itself fails, the case is recorded with an error and the run
continues. This is from pointing `--base-url` at a closed port:

```
$ evalkit run err.jsonl --base-url http://127.0.0.1:9 --out results/err.jsonl
FAIL  unreachable  (<urlopen error [Errno 61] Connection refused>)

0/1 cases passed. Results: results/err.jsonl
```

## Suite file format

One JSON object per line. Fields:

- `name` (required): unique id for the case. `diff` matches cases by name.
- `prompt` (required): the user message.
- `system` (optional): a system message.
- `assertions` (required): a list of assertion objects. A case with an empty list passes.

Assertion objects, in brief. Fields, exact failure messages, and one example each are in
[docs/assertions.md](docs/assertions.md).

| type | fields | passes when |
|---|---|---|
| `exact` | `value` | reply equals `value` exactly |
| `contains` | `value` | `value` is a substring of the reply |
| `not_contains` | `value` | `value` is not a substring of the reply |
| `regex` | `value` | `re.search(value, reply)` matches (multiline) |
| `json_schema` | `value` | reply parses as JSON and validates against the schema in `value` |
| `max_tokens` | `value` | completion token count is at most `value` |
| `judge` | `rubric`, optional `model` | a second model call with the rubric replies PASS |

Example lines:

```
{"name": "capital", "prompt": "Name the capital of France in one word.", "assertions": [{"type": "contains", "value": "Paris"}, {"type": "max_tokens", "value": 5}]}
{"name": "json-user", "prompt": "Return a JSON object with string field name and integer field age. No prose.", "assertions": [{"type": "json_schema", "value": {"type": "object", "required": ["name", "age"], "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}}}]}
{"name": "polite", "prompt": "Decline a meeting request politely.", "assertions": [{"type": "not_contains", "value": "no."}, {"type": "judge", "rubric": "The reply declines, gives no reason that sounds invented, and stays under three sentences."}]}
```

## Mock mode

`--mock` swaps the endpoint for a fake model with fixed behavior:

- A prompt that starts with `MOCK:` is echoed back without the prefix.
- Any other prompt gets the reply `mock reply for: <prompt>`.
- Judge calls return PASS when the reply being judged contains the word `pass`, else FAIL.
- `completion_tokens` is the whitespace word count of the reply.

This lets you write suites that exercise every assertion type with no key. The tests and
`examples/suite.jsonl` use it.

## Result file format

One JSON object per line: `name`, `prompt`, `model`, `ran_at`, `response`, `latency_ms`,
`completion_tokens`, `assertions` (each with `type`, `pass`, and `detail` or `error`),
and `pass`. `ran_at` is local time with a UTC offset. If the model call itself fails,
`response` and `latency_ms` are null, `assertions` is empty, `pass` is false, and an
`error` field holds the message.

## Architecture

Four pieces, three source files, under 250 lines of code excluding docstrings.

**Suite parsing** (`read_jsonl` in `evalkit/cli.py`). Reads a file line by line, skips
blank lines, and parses each remaining line as JSON. That is the whole parser. There is no
schema validation of the suite. A missing `name` or `prompt` raises `KeyError` when the
case runs. A missing assertion field is caught per assertion and recorded as an error on
that assertion.

**Model clients** (`evalkit/model.py`). Two classes with the same `chat(messages, model=None)`
method that returns `text`, `latency_ms`, and `completion_tokens`. `OpenAICompatible`
posts to `/chat/completions` with `urllib` and raises `ModelError` on any HTTP, network,
or response-shape problem. `MockModel` returns canned replies with no I/O. The runner and
the judge assertion only depend on the `chat` shape, so a new backend is one class.

**Runner** (`run_case` and `cmd_run` in `evalkit/cli.py`). For each case, build the
message list, call the model once, then call `check` for each assertion with the reply
and the token count. A `ModelError` from the model call marks the case failed with an
`error` and moves on. A `ModelError`, `ValueError`, or `KeyError` from a single assertion
marks that assertion failed with an `error` and continues with the next. The case passes
when every assertion passes. Results stream to the output file as each case finishes, so
a run killed halfway leaves a readable partial file.

**Assertion registry** (`evalkit/assertions.py`). One function, `check`, with an
`if` chain on `type`. The `TYPES` tuple lists the known names and is used in the unknown-type
error message. Each branch returns `(passed, detail)`. There is no plugin mechanism. Adding
a type means adding a branch, adding the name to `TYPES`, and documenting it.

**Reporters** (`summarize`, `cmd_report`, `diff_results`, `cmd_diff` in `evalkit/cli.py`).
Both read result files back with the same `read_jsonl`. `summarize` counts per assertion
type and computes min, median, p95, and max latency over cases that have one. `p95` is the
sorted value at index `round(0.95 * (n - 1))`, not an interpolation. `diff_results` matches
cases by name and reports case-level flips.

## Design decisions

**Why JSONL suites.** One case per line means you can `grep` a suite, append a case with
`echo >>`, and diff two suites with plain `diff`. Result files use the same shape for the
same reasons. Lines are parsed independently, so one broken line is easy to find. The cost
is that a case cannot span lines, which makes long schemas ugly. That trade was taken on
purpose.

**Why deterministic assertions are the default and `judge` is opt-in.** Six of the seven
types are plain string, regex, schema, or count checks. They are free, instant, and give
the same answer every time, so a flip in `diff` means the model output changed, not the
grader. `judge` costs a second model call, depends on the judge model, and can flip on its
own between runs. You add it per assertion when a rubric is the only way to express what
you want, and the result file records the judge's verdict text so you can see what it
said.

**What `diff` compares.** It matches cases by `name` across two result files. A case is
`fixed` when its case-level `pass` went from false to true, `broken` for the reverse.
`added` and `removed` are names present in only one file. For fixed and broken cases it
also lists the positional indexes of assertions whose `pass` differs, pairing them by
position with `zip`. That means: a case that stays failing while a different assertion
inside it starts failing is not reported, and if you reorder or add assertions between
runs the indexes will not line up. It compares outcomes only. It does not compare reply
text, latency, or token counts.

**Why results stream to disk.** Each result line is written as soon as the case finishes.
A long run against a slow endpoint that dies at case 40 of 100 leaves 40 usable lines.

**Why `urllib` and not a client library.** The request is one POST with a JSON body. The
standard library covers it, keeps the dependency list to `jsonschema`, and works against
any server that accepts the same body shape.

## Tests

```
.venv/bin/python -m pytest -q
```

Eleven tests. They cover every assertion type, the diff logic, a full mock run through
`run`, `report`, and `diff`, output-directory creation, and the error path for a 200
response with an unexpected body.

## License

MIT
