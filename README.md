# Understudy

Understudy is a small record-once, replay-many computer-use system. An LLM
drives a live, intentionally legacy-style banking UI during discovery. The
successful run is normalized into a typed capability artifact. Later calls
replay that artifact with Playwright and no model in the decision loop.

The implemented vertical slice accepts a member ID, searches a synthetic core
banking application, opens the matching member, and returns the Savings balance
as integer cents plus an ISO currency code. It also demonstrates a typed
not-found business outcome, transient-condition handling, policy enforcement,
sanitized evidence, and same-session human handoff for an expired session.

This repository contains synthetic data only. Do not enter real credentials,
customer data, tokens, or PII into the sample application.

## Architecture at a glance

- `src/understudy/discovery/` is the LLM-driven observe → decide → act path.
  It sends accessible control descriptions and temporary control IDs to the
  model, then executes only a constrained action schema.
- `src/understudy/artifact/` contains the strict, versioned Pydantic contract
  and cross-reference validation.
- `src/understudy/surface/` separates semantic replay operations from the
  Playwright web implementation.
- `src/understudy/replay/` is the deterministic production path: policy gate,
  target resolution, actions, condition polling, runtime outcomes, retries,
  checkpoint verification, and typed parsing.
- `src/understudy/handoff.py` owns the explicit automation/human control lease
  and records operator actions in the same browser session.
- `target_app/` is a local Flask proxy for a legacy core-banking UI. It uses an
  iframe, server-rendered forms, tables, unstable-looking field names, and no
  test IDs.
- `tests/fixtures/lookup_member_savings.hand-authored.json` is the permanent,
  reviewed test fixture. A real generated artifact belongs under
  `capabilities/`; the two files have different jobs and both are retained.

See [REPORT.md](REPORT.md) for design decisions and trade-offs.

## Setup

Python 3.11 or newer is required. The following uses the existing Conda
environment name used during development; a virtualenv works equally well.

```bash
cd understudy
conda activate understudy
python -m pip install -e '.[dev]'
playwright install chromium
```

Only discovery needs a model key. Understudy supports Anthropic directly and
tool-capable models through OpenRouter; neither path requires a provider SDK.

For OpenRouter, create a key at <https://openrouter.ai/settings/keys>, ensure
the account has credit, and export it only in the terminal that will run
discovery:

```bash
export OPENROUTER_API_KEY='your-openrouter-key'
python -c "import os; print('configured' if os.getenv('OPENROUTER_API_KEY') else 'missing')"
```

The default pinned OpenRouter model is `nex-agi/nex-n2.5-pro:free`, a free
model that currently advertises `tools` and `tool_choice` support. A pinned
model makes discovery evidence more reviewable than the random
`openrouter/free` router. Free-model availability and rate limits can vary; a
paid Claude model remains available as an explicit override.

To use Anthropic directly instead:

```bash
export ANTHROPIC_API_KEY='your-key'
```

Never commit `.env` files or keys. Validation, deterministic replay, and all
non-discovery tests run without any model key or live service.

## End-to-end demo

Start the synthetic application in terminal 1:

```bash
cd understudy
conda activate understudy
python -m flask \
  --app target_app.app:app \
  run \
  --host 127.0.0.1 \
  --port 5055
```

In terminal 2, perform the required genuine LLM-driven discovery run:

```bash
cd understudy
conda activate understudy
understudy discover \
  --provider openrouter \
  --model nex-agi/nex-n2.5-pro:free \
  --goal 'Look up member 00123 and read the current Savings balance' \
  --target http://127.0.0.1:5055/app \
  --template tests/fixtures/lookup_member_savings.hand-authored.json \
  --input member_id=00123 \
  --output capabilities/lookup_member_savings.generated.json \
  --evidence-dir evidence
```

The model selects controls from fresh live observations; the runner types,
clicks, and reads the real UI. It writes a generated capability, a sanitized
decision log, an artifact copy, and a final screenshot. `--model` can override
the provider-specific default, and `--headed` makes the browser visible. The
`--model` option may be omitted for the documented defaults. For paid Claude
through OpenRouter, use `--model anthropic/claude-4.6-sonnet`; for direct
Anthropic access, use `--provider anthropic --model claude-sonnet-4-6`.

Validate the generated artifact, then prove replay does not require the key:

```bash
understudy validate capabilities/lookup_member_savings.generated.json
unset ANTHROPIC_API_KEY
unset OPENROUTER_API_KEY
understudy replay \
  capabilities/lookup_member_savings.generated.json \
  --input member_id=00123 \
  --runtime base_url=http://127.0.0.1:5055 \
  --evidence-dir evidence
```

Expected outputs are `savings_balance_cents: 125050` and `currency: USD`.
The financial value is returned to the caller but redacted in persisted
evidence according to the artifact's output policy.

Exercise a legitimate business outcome rather than a crash:

```bash
understudy replay \
  capabilities/lookup_member_savings.generated.json \
  --input member_id=99999 \
  --runtime base_url=http://127.0.0.1:5055 \
  --evidence-dir evidence
```

The result has `status: business_outcome` and
`condition_code: MEMBER_NOT_FOUND`.

## Human-handoff demo

With the Flask app still running, start the interactive headed demo:

```bash
understudy handoff-demo \
  --artifact capabilities/lookup_member_savings.generated.json \
  --target 'http://127.0.0.1:5055/app?inject=expired' \
  --evidence-dir evidence
```

The artifact's runtime monitor detects the injected `SESSION_EXPIRED` state
inside a real replay and invokes the handoff handler. Understudy pauses that
engine, records the owner as `human`, and leaves the same browser page open.
Click **Resume session** in that browser, return to the terminal, and press
Enter. Understudy verifies the artifact's resume condition, transfers ownership
back to `automation`, and continues the same replay through its final
checkpoint. `evidence/handoff-run.json` contains the transfer ledger, sanitized
resumed result, and before/after screenshot paths. Click/input events are
recorded, but input values are never captured.

## Tests

Run the fast deterministic suite, which needs no key and no browser service:

```bash
pytest -q
```

Run the complete suite, including real local-browser integration tests:

```bash
UNDERSTUDY_E2E=1 pytest -q
```

The E2E tests cover primary and fallback locator resolution, legitimate absence
of detection-only targets, relational table targeting, successful replay,
not-found handling, replay with both provider keys removed, and same-session
handoff. If Chromium is missing, rerun `playwright install chromium`.

## Useful commands

```bash
understudy --help
understudy discover --help
understudy replay --help
understudy handoff-demo --help
```
