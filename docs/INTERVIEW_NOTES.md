# Understudy interview notes

These notes explain what the project does, why it is designed this way, and how
to walk through the code in an interview. They are deliberately more detailed
than `REPORT.md`, which is kept close to the assessment's requested 1-3 page
length.

## Thirty-second explanation

Understudy is a record-once, replay-many computer-use system for software with
no API. During discovery, an LLM sees a constrained accessibility-oriented
snapshot of a live legacy-style UI and chooses typed actions. A successful run
is normalized into a strict, versioned capability artifact. In production-style
replay, the system executes that artifact deterministically with Playwright,
without an LLM, while enforcing policy, evaluating conditions, parsing typed
outputs, handling known runtime outcomes, and escalating unsafe states to a
human who takes over the same browser session.

The main design principle is: the model discovers; the artifact becomes the
reviewed contract; deterministic replay invokes it cheaply and reliably.

## Assessment coverage

| Assessment requirement | What Understudy provides | Where to show it |
| --- | --- | --- |
| Goal and target input | `understudy discover` accepts a natural-language goal, target URL, typed inputs, provider, and model. | `cli.py`, README discovery command |
| Real LLM loop | Each live observation is sent to Anthropic or OpenRouter; the model returns one typed tool decision; Playwright acts on the chosen live control. | `discovery/provider.py`, `discovery/engine.py`, `discovery/surface.py`, `evidence/discovery-run.json` |
| Stopping conditions | Discovery has a fixed maximum step count, wall-clock deadline, expected workflow grammar, finish decision, and escalation decision. | `DiscoveryRunner` |
| Structured artifact | Strict Pydantic schema with version, contract, targets, steps, inputs, outputs, checkpoint, conditions, policy, and provenance. | `artifact/models.py`, generated JSON |
| Deterministic replay | Fixed artifact steps execute through the surface adapter; no provider object exists on this path. | `replay/engine.py`, successful replay evidence |
| Stable targeting | Accessibility, text, attribute, CSS fallback, and relational-table strategies; cardinality is checked and fallback is reported as degraded. | `surface/playwright.py`, target definitions |
| Typed outputs and checkpoint | Money text becomes integer cents plus ISO currency; final checkpoint verifies member identity and both outputs. | read action and `success_checkpoint` |
| Business outcome | Unknown member returns `business_outcome/MEMBER_NOT_FOUND`, not a crash. | runtime conditions and not-found replay evidence |
| Recoverable condition | Loading state uses bounded wait-until-hidden recovery. | `RuntimeConditionMonitor` |
| Hard failure | Application-error condition raises a typed hard failure; CLI records safe metadata and a redacted screenshot. | `runtime.py`, `evidence.py` |
| Policy | Inputs, runtime bindings, route origins, route refs, action types, step count, runtime, and risk classes are checked before replay. Discovery validates its entry route and input/action contract before navigation. | `ReplayEngine._validate_request`, `DiscoveryRunner._validate_request` |
| Sensitive-data handling | Runtime inputs and raw transcripts are omitted; financial outputs and screenshots are redacted; arbitrary exception text is withheld. | `evidence.py`, discovery evidence |
| Human handoff | Actual `SESSION_EXPIRED` monitoring invokes a handler inside replay, cedes the same Playwright page to a human, verifies resume, and continues replay. | `handoff.py`, `ReplayEngine._check_runtime`, handoff evidence |
| Heterogeneous surfaces | Replay depends on a `Surface` protocol; web details stay in `PlaywrightWebSurface`; contexts can map to frames now and windows/panes later. | `surface/base.py`, REPORT section 4 |
| Multi-tenant design | Base artifact is keyed by app family/version; narrow target/context/route overrides and degraded-resolution telemetry are proposed. | REPORT section 4 |
| Public repository and evidence | Public GitHub repository with generated artifact, discovery log/screenshot, success and not-found replay logs, and handoff record/screenshots. | repository root and `evidence/` |

## What is intentionally constrained

These are conscious cuts, not hidden claims:

- Discovery handles one known member-balance workflow. The LLM chooses the live
  control on each fresh observation, but code enforces the expected semantic
  action and target sequence. This is real model-driven interaction without
  pretending to be a general browser agent.
- The generated artifact starts from a reviewed template and normalizes the
  observed roles/names plus provenance into that contract. The hand-authored
  fixture remains separate so tests never depend on a model run.
- The operator UI is a headed browser and terminal prompt. The control lease,
  same-session behavior, action capture, resume verification, and evidence are
  real; routing/authentication UI is mocked.
- Desktop and multi-tenant support are designed at seams but are not built,
  which the assignment explicitly permits.
- The policy is embedded in the artifact. Production must intersect it with an
  independently administered tenant policy and enforce browser-network egress.
- No optional stretch goal was added merely for breadth. The artifact contains
  an approval state, but unattended replay is not yet gated by a signed external
  approval service.

## Architecture walkthrough

### Discovery path

1. The CLI loads and validates the reviewed template.
2. `create_discovery_model` constructs a provider only for discovery.
3. `DiscoveryRunner` validates the goal, target entry route, typed inputs, and
   required action classes before any navigation.
4. `PlaywrightDiscoverySurface.observe` scans visible controls in the page and
   every frame. It derives role/name information and assigns temporary IDs such
   as `c1`; IDs are valid only for the current observation.
5. The provider sends the goal, observation, and sanitized history through a
   forced tool/function schema. The model cannot return arbitrary code, URLs,
   or selectors.
6. Pydantic parses the response into exactly one decision variant.
7. The runner checks that the decision matches the next permitted semantic
   action and target, then code supplies any runtime value and performs the
   action.
8. After the read, code parses the financial value and verifies the same final
   checkpoint used by replay.
9. `_compile_artifact` deep-copies the reviewed contract, updates observed
   primary accessibility descriptions, records model-discovery provenance,
   and validates the whole artifact again.
10. Evidence stores sanitized decision summaries, provider/model identity, a
    redacted screenshot, and no raw transcript or runtime values.

Why temporary control IDs? They let the model choose from what is actually
visible without granting it authority to invent a selector. Code retains the
real locator behind each ID and rejects stale or unknown IDs.

### Replay path

1. The CLI loads JSON directly into `CapabilityArtifact`.
2. `ReplayEngine._validate_request` checks the invocation and policy before
   actions begin.
3. For each fixed `Step`, the engine waits for its precondition, executes its
   typed action, and waits for its postcondition.
4. `ActionExecutor` dispatches by the concrete action model. It has no LLM and
   no decision-making prompt.
5. `PlaywrightWebSurface` resolves the target's primary strategy first. It only
   accepts a locator whose count falls in the declared range. A fallback is
   marked degraded.
6. `ConditionWaiter` polls instead of sleeping blindly. During the loop it asks
   `RuntimeConditionMonitor` about exceptional states.
7. Known conditions either return a business outcome, recover within a bound,
   request intervention, or raise a hard failure.
8. A read action parses UI text into declared output fields.
9. The final checkpoint verifies the end-to-end promise independently of local
   step postconditions.
10. Required outputs are checked again for presence, declared Python type, and
    enum membership.
11. The caller receives typed output. Persisted replay evidence obeys each
    output's log policy.

Why no LLM fallback during replay? The production path must be predictable,
reviewable, inexpensive, and policy-bounded. An open-ended model fallback would
erase the main value of the artifact. A future fallback should be single-step,
bounded, separately approved, and fully recorded.

### Handoff path

`SESSION_EXPIRED` is declared in the artifact, not hard-coded into the engine.
The runtime monitor raises `InterventionRequired`; the engine enriches it with
capability, goal, and current step. If no handler is configured, replay stops
cleanly. The demo configures a handler that creates a `HandoffSession`, captures
a before screenshot, and changes the exclusive owner from automation to human.

The human acts in the existing headed Playwright page. Browser context, cookies,
frame state, and page identity are preserved. Event listeners record click/input
metadata but never input values. When the operator presses Enter, code evaluates
the artifact's resume condition. Only then does ownership return to automation,
the interrupted wait continues, and replay reaches the final checkpoint. The
handoff JSON records both transfers and the redacted resumed result.

## How `artifact/models.py` was built

The file was built bottom-up so every larger object is composed from already
valid smaller objects:

```text
StrictModel and constrained primitives
    -> locator strategy variants
    -> Target and SurfaceContext
    -> condition variants
    -> action and parser variants
    -> Step
    -> capability/target/input/output metadata
    -> runtime-condition taxonomy
    -> policy and provenance
    -> CapabilityArtifact aggregate validation
```

This ordering matters. If the top-level artifact had been written first as a
large collection of dictionaries, invalid combinations would spread everywhere
and error messages would be vague. Bottom-up models establish local invariants
before cross-object references are checked.

### `StrictModel`

Every schema class inherits `StrictModel`, whose Pydantic configuration uses
`extra="forbid"`. This rejects misspelled or invented JSON fields instead of
silently ignoring them. For an automation contract, silent acceptance is
dangerous because a reviewer may believe a policy or condition is active when
the runtime discarded it.

### Literals, unions, and discriminators

`Literal` fields make tags and policy vocabulary closed sets. For example, an
action type must be `navigate`, `enter_text`, `activate`, `read`, or
`press_key`; an arbitrary `run_script` action cannot validate.

Related variants use this pattern:

```python
Action = Annotated[
    Union[NavigateAction, EnterTextAction, ActivateAction, ReadAction,
          PressKeyAction],
    Field(discriminator="type"),
]
```

Pydantic reads the `type` tag and selects exactly one class. Each variant then
requires only fields that make sense for that operation. This is safer and more
readable than one action class with ten optional fields, which could allow
nonsensical combinations such as `type="read"` plus a navigation URL.

The same pattern is used for locator strategies (`kind`), table row matching,
table selection, conditions, and runtime conditions (`classification`). It also
makes execution exhaustive: `ActionExecutor` uses `isinstance` branches and
`assert_never`, so adding a new schema variant forces deliberate runtime work.

### Fields and local validators

`Field` expresses simple bounds close to the data:

- match counts cannot be negative;
- lists that must contain at least one strategy use `min_length=1`;
- timeouts are positive;
- retry counts are at least one.

`model_validator(mode="after")` expresses relationships between fields after
Pydantic has parsed them. Examples:

- `MatchCount.min` cannot exceed `max`;
- a text strategy requires exactly one of literal `value` or `value_from`;
- an attribute strategy requires exactly one literal value or template;
- a retry cannot repeat an action declared non-idempotent.
- non-public inputs and outputs must use redacted logging, and only string
  outputs may define string enums.

`default_factory=list` creates a fresh list for every instance. A bare mutable
default can accidentally share state between model instances; the factory
avoids that class of bug.

### Locator strategies

- `AccessibilityStrategy`: role plus accessible name. This is preferred because
  it expresses user-visible meaning and can map to desktop accessibility APIs.
- `TextStrategy`: visible text, optionally scoped to a CSS region. Useful for
  legacy status messages without semantic roles.
- `AttributeStrategy`: stable application attributes such as a form control's
  `name`; supports parameterized templates.
- `CssStrategy`: controlled last-resort fallback for structure that lacks
  useful semantics. Generated DOM paths are intentionally avoided.
- `TableRelationStrategy`: finds a table by meaning, finds the correct row by a
  column value or row label, then selects a descendant action or named column.
  This prevents selecting the wrong account because its row position changed.

`Target` groups strategies behind one semantic ID. `expected_matches` makes
ambiguity explicit. `role_in_flow` distinguishes actionable controls from
detection-only signals. `DriftPolicy` names the primary, says fallbacks become
observable degradation, and defines whether no match is failure or legitimate
absence.

`SurfaceContext` makes the iframe a separately resolvable object. Targets point
to the context ID rather than repeating a frame path. A tenant override can
therefore change one context instead of every nested target. A desktop adapter
could give the same conceptual object a window or pane locator.

### Conditions

Conditions are data, so the same evaluator supports preconditions,
postconditions, final checkpoints, runtime detection, and handoff resume checks.
The variants cover visibility, absence, enabled state, element value/text
equality, typed output checks, runtime-binding presence, and recursive `all`.

`AllCondition` refers recursively to `Condition`. `model_rebuild` resolves that
forward reference after the union exists. Keeping waits and assertions out of
the action union avoids two ways to express the same concept: the waiter polls
a condition, while pre/post/checkpoint placement says why it is being checked.

### Actions, parsers, and steps

Actions express intent without implementation-specific selectors. A navigation
references a reviewed route; text entry references a target and an invocation
value; activation references a target; read references a target and typed
parser; press-key optionally references a target. `MoneyParser` names both the
expected representation and the output slots it produces.

A `Step` makes correctness and safety local:

- `intent` explains why the step exists;
- `action` says what deterministic operation runs;
- `risk` lets policy decide whether unattended execution is legal;
- `precondition` prevents acting in the wrong state;
- `postcondition` proves the intended transition;
- `runtime_condition_check` documents monitoring during waits;
- `timeout_ms` bounds waiting;
- `retry` states attempts, backoff, idempotency, whether to repeat the action,
  and eligible failure reasons.

### Contract metadata

`CapabilityMetadata` answers what the capability is, its version, lifecycle
state, and overall risk. `ApplicationTarget` identifies the surface and vendor
family, compatible versions, runtime URL bindings, reviewed route catalog, and
entry point. `InputDefinition` and `OutputDefinition` give the calling agent a
typed contract plus sensitivity and log behavior. Member ID is a string, not an
integer, because leading zeros are meaningful.

The balance output is integer cents rather than floating point. This is exact,
currency-safe, and easy for callers to validate. Currency is a separate ISO
code so the numeric value is not ambiguous.

### Runtime-condition taxonomy

All runtime conditions have code, priority, phases, and a detection condition,
then diverge by classification:

- `BusinessOutcomeRuntimeCondition`: expected caller-meaningful result;
- `RecoverableRuntimeCondition`: bounded known recovery;
- `InterventionRuntimeCondition`: automation must cede control;
- `HardFailureRuntimeCondition`: stop with category and evidence policy.

Priority makes simultaneous states deterministic. Detection targets allow zero
matches because not seeing an error is normal. Monitoring runs during waits,
not only after timeout, so transient or expired-session UI is caught while it
exists.

### Policy and provenance

`PolicyRequirements` defines origins, routes, action classes, budgets, risk
handling, model constraints, and data handling. Declaring policy in the
artifact makes review possible; runtime enforcement makes it real. The report
is explicit that a production system must intersect this with policy controlled
outside the artifact.

`Provenance` distinguishes the permanent hand-authored fixture from a genuine
model-discovered artifact and links the latter to its discovery run. This is why
the generated artifact never replaces the fixture: one is evidence, the other
is a deterministic testing contract.

### Aggregate validation

`CapabilityArtifact.validate_contract_references` is the final integrity pass.
It verifies:

- unique step IDs, runtime-condition codes, and locator-strategy IDs;
- declared entry and allowlisted routes;
- valid context and target references;
- existence of every primary strategy;
- valid value references in actions, conditions, locators, routes, and origin
  templates;
- output-condition type agreement;
- actions never target detection-only targets;
- read parser outputs are declared;
- money parser outputs have the required integer/string types;
- all checkpoint, runtime-detection, recovery, and resume references exist.

Local validation answers "is this object internally meaningful?" Aggregate
validation answers "does this entire graph join together?" Both are needed.

## One step traced end to end

For `read_savings_balance`:

1. The step precondition asks whether `savings_balance_cell` is visible.
2. The resolver enters `member_workspace` by resolving the iframe.
3. The primary table relation finds the `Accounts` table, the row whose
   `Account type` is `Savings`, and its `Current balance` cell.
4. The read action extracts text through `Surface.read_text`.
5. `parse_money` requires an exact US-dollar shape and converts it to integer
   cents plus `USD`. Malformed financial text is never echoed in its exception.
6. The parser writes only the output names declared in the artifact.
7. The postcondition confirms the amount is an integer and currency is `USD`.
8. The final checkpoint checks those outputs again together with the correct
   member detail page.
9. The caller receives `125050` and `USD`; evidence stores `[REDACTED]` for the
   balance and may retain public currency metadata.

## Likely interview questions

### Is discovery truly LLM-driven if the flow is constrained?

Yes, but narrowly. The provider receives each fresh live observation and picks
the concrete control and typed next action. Code verifies that choice against a
known workflow grammar. This proves the required observe-decide-act boundary
without giving a model unrestricted authority in a banking scenario. The cut
is stated openly.

### Why not save the model transcript and replay it?

A transcript is untyped, contains runtime values, couples replay to one prompt
and provider, and gives weak review guarantees. The capability artifact stores
semantic intent, parameter references, locators, conditions, and parsers. It is
provider-independent and safe to validate before execution.

### Why keep both hand-authored and generated artifacts?

The hand-authored file is a stable unit/E2E fixture with no API dependency. The
generated file proves the real LLM run. Replacing the fixture with generated
output would make deterministic tests depend on probabilistic history.

### What makes replay deterministic?

Fixed ordered steps, typed actions, reviewed routes, parameter references,
bounded semantic locator strategies, explicit cardinality, condition polling,
bounded retries, runtime-condition priority, output parsing, and a final
checkpoint. No provider is constructed and both provider keys are removed in
an E2E test.

### Why use accessible names when the app has a DOM?

Role/name locators express what a human sees, survive many markup changes, and
map conceptually to native desktop accessibility APIs. The system still has
controlled legacy fallbacks because real enterprise markup is often poor.

### Why are detection targets allowed to be absent?

An error marker should usually not exist. Treating zero matches as a locator
failure would make the normal state fail. Action targets have a different
contract: they must resolve uniquely before interaction.

### Why is not-found not an exception?

It is a legitimate answer to the caller's question. Returning a typed business
outcome lets an upstream agent choose a different business action without
confusing absence with system malfunction.

### Why separate postconditions from the final checkpoint?

A postcondition proves one local transition. The final checkpoint proves the
capability's complete promise: correct record plus well-formed declared outputs.
Without it, five individually successful clicks could still produce the wrong
business result.

### What is the biggest production limitation?

Trust policy is not independently administered. A production runtime must
intersect artifact requests with tenant policy and enforce network egress below
Playwright. Next are signed artifact approval, durable workers, and an
authenticated operator service with expiring ownership leases.

## Suggested code walkthrough order

When presenting, do not begin with all 700+ lines of `models.py`. Use this path:

1. Show the README demo command and the architecture diagram.
2. Show one readable artifact step plus its target and final checkpoint.
3. Show `StrictModel`, one locator union, `Condition`, `Action`, `Step`, and the
   aggregate validator in `models.py`.
4. Show the `Surface` protocol and the primary/fallback resolver.
5. Show `ReplayEngine.run`, then condition polling and runtime classification.
6. Show the discovery observation and forced tool decision.
7. Show the generated provenance and sanitized discovery evidence.
8. Show the success and not-found replay records.
9. Show the ownership transfer ledger and resumed replay in handoff evidence.
10. End with the explicit production limits in REPORT sections 6 and 7.

The strongest interview stance is not "everything is production-ready." It is:
"Every must-have has a thin, executable version; the trust boundaries and
remaining production work are explicit."
