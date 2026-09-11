# Understudy

Understudy is a record-once, replay-many computer-use automation system.

An LLM discovers how to perform a workflow through a live user interface.
Understudy records that run as a typed capability artifact and subsequently
replays it deterministically without an LLM in the decision loop.

## Status

Work in progress. The repository currently contains:

- a strict, cross-reference-validated capability artifact contract;
- a hand-authored member-savings fixture;
- a legacy-style Flask target application; and
- a platform-neutral surface contract with a Playwright web adapter.

Run the deterministic test suite:

```bash
pytest -q
```

Run the browser integration tests (requires Playwright Chromium):

```bash
UNDERSTUDY_E2E=1 pytest tests/test_playwright_surface.py -q
```

The next milestone is a deterministic replay engine that evaluates artifact
conditions and executes artifact actions exclusively through the surface
contract.
