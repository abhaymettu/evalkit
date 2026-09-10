# evalkit

A minimal assertion runner for LLM outputs.

You write a suite file. Each line is a prompt plus a list of assertions. evalkit sends
the prompt to any OpenAI-compatible chat endpoint, checks the reply against the
assertions, and writes one result line per case. You can then print a summary of a run
or compare two runs to see which cases flipped.

## What it does

- Runs a JSONL suite against a chat completions endpoint.
- Checks seven assertion types: `exact`, `contains`, `not_contains`, `regex`,
  `json_schema`, `max_tokens`, `judge`.
- Records the reply, per-assertion pass or fail, and the measured request latency.
- Reports pass and fail counts per assertion type and latency stats.
- Diffs two result files and lists what got fixed, what broke, what was added or removed.
- Has a `--mock` mode with a deterministic fake model so the whole pipeline runs offline.

## What it does not do

- It is not a benchmark. It has no built-in datasets and no scores to compare across models.
- No leaderboards, no dashboards, no history beyond the result files you keep.
- No retries, no concurrency, no rate limiting. Cases run one at a time.
- No token counting of its own. `max_tokens` uses the `completion_tokens` value the API
  returns. If the API omits usage, it falls back to a whitespace word count and says so
  in the detail.
- `judge` assertions are only as good as the judge prompt and the judge model. A PASS
  from the judge is the judge's opinion, not ground truth.
- The six deterministic assertion types need no model key. The `judge` type makes a second
  model call and needs a key unless you are in mock mode.

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
a local Ollama or vLLM server.

Run the same suite offline with the fake model:

```
.venv/bin/evalkit run examples/suite.jsonl --mock --out results/run1.jsonl
```

Summarize a run:

```
.venv/bin/evalkit report results/run1.jsonl
```

Compare two runs:

```
.venv/bin/evalkit diff results/run1.jsonl results/run2.jsonl
```

Exit codes: `run` returns 1 if any case failed, `diff` returns 1 if any case broke.

## Suite file format

One JSON object per line. Fields:

- `name` (required): unique id for the case. `diff` matches cases by name.
- `prompt` (required): the user message.
- `system` (optional): a system message.
- `assertions` (required): a list of assertion objects.

Assertion objects:

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

The judge call sends a fixed system prompt asking for a one-word PASS or FAIL, then the
rubric and the reply. The assertion passes when the judge's reply starts with PASS. Set
`model` on the assertion to use a different judge model than the one under test.

## Mock mode

`--mock` swaps the endpoint for a fake model with fixed behavior:

- A prompt that starts with `MOCK:` is echoed back without the prefix.
- Any other prompt gets the reply `mock reply for: <prompt>`.
- Judge calls return PASS when the reply being judged contains the word `pass`, else FAIL.

This lets you write suites that exercise every assertion type with no key. The tests and
`examples/suite.jsonl` use it. The example suite includes one deliberate failure so the
report and diff have something to show.

## Result file format

One JSON object per line: `name`, `prompt`, `model`, `ran_at`, `response`, `latency_ms`,
`completion_tokens`, `assertions` (each with `type`, `pass`, and `detail` or `error`),
and `pass`. If the model call itself fails, `response` and `latency_ms` are null and an
`error` field holds the message.

## Sample report output

From `evalkit run examples/suite.jsonl --mock --out results/run1.jsonl` followed by
`evalkit report results/run1.jsonl`:

```
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

Latency is measured around each request. In mock mode it rounds to zero.

Sample `diff` output after fixing the failing case in a second run:

```
fixed   expected-failure  (assertion index: [0])

fixed 1  broken 0  added 0  removed 0
```

## Tests

```
.venv/bin/python -m pytest -q
```

The suite covers every assertion type, the diff logic, and a full mock run through
`run`, `report`, and `diff`.

## License

MIT
