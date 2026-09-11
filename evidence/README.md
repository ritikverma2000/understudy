# Evidence manifest

This directory is populated by the real demo commands in the repository root
README. A complete submission should retain:

- `discovery-run.json` — sanitized decisions from the genuine LLM-driven run;
- `lookup_member_savings.generated.json` — the artifact copied from
  `capabilities/`;
- `discovery-*-final.png` — the discovery completion state;
- `replay-*.json` — deterministic success and not-found replay records; and
- `handoff-run.json` plus its before/after screenshots — the ownership
  transfer demonstration.

Generated evidence must come from the CLI. Unit-test fake-model output is not
accepted here as a substitute for the required live discovery run. Runtime
inputs, raw model transcripts, credentials, tokens, and financial values must
not be committed.
