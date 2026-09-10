# Assertion reference

Every assertion is a JSON object inside a case's `assertions` list. The `type` field
picks the check. The other fields depend on the type. `check` in `evalkit/assertions.py`
implements all of them.

Each check returns a pass flag and a `detail` string. For most types `detail` is empty on
pass and holds the reason on failure. `max_tokens` always fills it. The runner stores both
in the result file. If a check raises instead of returning, the runner records the message
in an `error` field on that assertion, marks it failed, and moves on to the next one.

All strings below were produced by running the code. Long values in `exact` are cut to
200 characters in the message. Judge replies are cut to 200 characters too.

## exact

The reply must equal `value` character for character. No trimming, no case folding.

```
{"type": "exact", "value": "42"}
```

Failure detail: `expected '42', got 'forty-two'`

## contains

`value` must appear somewhere in the reply as a substring. Case-sensitive.

```
{"type": "contains", "value": "Paris"}
```

Failure detail: `'Paris' not found`

## not_contains

`value` must not appear in the reply as a substring. Case-sensitive.

```
{"type": "not_contains", "value": "London"}
```

Failure detail: `'London' found`

## regex

`value` is a Python regular expression. The check is `re.search` with the `MULTILINE`
flag, so `^` and `$` match at line boundaries and the pattern can match anywhere in the
reply. Remember to double the backslashes inside JSON.

```
{"type": "regex", "value": "^\\d{3}$"}
```

Failure detail: `no match for /^\d{3}$/`

An invalid pattern raises `re.error`, which the runner does not catch. Test patterns
before adding them to a suite.

## json_schema

The reply must parse as JSON and validate against the schema in `value`. Validation uses
the `jsonschema` library. The whole reply is parsed, so a reply that wraps JSON in prose or
code fences fails.

```
{"type": "json_schema", "value": {"type": "object", "required": ["age"], "properties": {"age": {"type": "integer"}}}}
```

Failure detail when the reply is not JSON:
`not JSON: Expecting value: line 1 column 1 (char 0)`

Failure detail when it is JSON but does not match:
`schema: 'x' is not of type 'integer'`

The text after `schema:` is the validator's own message for the first violation found.

## max_tokens

The completion token count must be at most `value`. The count comes from the
`usage.completion_tokens` field of the API response. If the server did not return usage,
the check falls back to counting whitespace-separated words in the reply and says so.
`detail` is always filled, on pass and on fail, so the count and its source are on record.

```
{"type": "max_tokens", "value": 5}
```

Pass detail: `2 tokens (completion_tokens from response)`

Failure detail with API usage: `6 tokens (completion_tokens from response), limit 5`

Failure detail with fallback: `6 tokens (whitespace count, no usage in response), limit 5`

The mock model reports a whitespace word count as `completion_tokens`, so in mock mode the
detail always says `completion_tokens from response`.

## judge

Makes a second model call. The system message is fixed:

```
You are a strict grader. Reply with exactly one word: PASS or FAIL.
```

The user message is the rubric, a blank line, and the reply under test:

```
Rubric:
<rubric>

Response:
<reply>
```

The assertion passes when the judge's reply, stripped and upper-cased, starts with `PASS`.
Anything else is a fail, including an empty reply or a reply that explains before
answering.

Fields: `rubric` (required) and `model` (optional). `model` overrides the model name for
the judge call only, so you can grade with a different model than the one under test. The
call goes to the same endpoint and uses the same key.

```
{"type": "judge", "rubric": "The reply declines politely and stays under three sentences."}
```

Pass detail: `judge said 'PASS'`

Failure detail: `judge said 'FAIL'`

Without a model, for example when calling `check` directly from Python without passing
one, the check raises `ModelError("judge assertion needs a model")`. Inside a run the
runner always passes the model in use, so this only happens in library use.

In mock mode the judge returns `PASS` when the judged reply contains the word `pass`
(case-insensitive) and `FAIL` otherwise. The rubric is ignored.

## Unknown types

A `type` not listed above raises `ValueError`. The runner records it on the assertion:

```
{"type": "nope", "pass": false, "error": "unknown assertion type 'nope'; known: exact, contains, not_contains, regex, json_schema, max_tokens, judge"}
```

A missing required field, for example `exact` without `value`, raises `KeyError` and is
recorded the same way with the field name as the message.
