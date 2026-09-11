# Understudy

Understudy is a record-once, replay-many computer-use automation system.

An LLM discovers how to perform a workflow through a live user interface.
Understudy records that run as a typed capability artifact and subsequently
replays it deterministically without an LLM in the decision loop.

## Status

Work in progress. The repository currently contains:

- a strict, cross-reference-validated capability artifact contract;
- a hand-authored member-savings fixture;
- a legacy-style Flask target application;
- a platform-neutral surface contract with a Playwright web adapter;
- a deterministic replay engine with policy gates, condition polling,
  runtime-condition handling, retries, and typed output extraction; and
- a JSON-producing CLI for artifact validation and replay.

## CLI

Validate the permanent hand-authored fixture:

```bash
understudy validate \
  tests/fixtures/lookup_member_savings.hand-authored.json
```

Start the target application in one terminal:

```bash
python -m target_app.app
```

Replay a successful lookup from another terminal:

```bash
understudy replay \
  tests/fixtures/lookup_member_savings.hand-authored.json \
  --input member_id=00123 \
  --runtime base_url=http://127.0.0.1:5000
```

Use `--headed` to watch the deterministic browser replay.

Run the deterministic test suite:

```bash
pytest -q
```

Run the browser integration tests (requires Playwright Chromium):

```bash
UNDERSTUDY_E2E=1 pytest tests/test_playwright_surface.py -q
```

The replay engine executes artifact actions exclusively through the surface
contract; no model participates in replay decisions.
