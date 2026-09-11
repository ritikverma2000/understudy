# 1. Architecture

Understudy implements one narrow end-to-end thread: a natural-language goal
drives a synthetic legacy banking UI once; that successful discovery is
normalized into a reviewed capability artifact; subsequent invocations execute
the artifact without an LLM. The target is deliberately awkward rather than a
modern test-friendly page: a Flask application renders an iframe, server-side
forms, nested tables, and opaque field names without test IDs. This exercises
the same targeting and synchronization concerns that matter in older banking
software without using a real institution or real data.

The main boundary is `Surface`. Replay understands semantic operations such as
navigate, resolve target, activate, read text, and read value; it does not know
Playwright locators. `PlaywrightWebSurface` implements those operations for the
web. Above it, `ReplayEngine` owns policy checks, ordered execution, bounded
waiting/retries, runtime-condition monitoring, output parsing, and the final
checkpoint. This separation keeps the reusable flow independent of the
mechanism used to perceive and operate the UI.

Discovery is intentionally a separate path. On every step it observes visible
controls across the page and frames, assigns ephemeral IDs, and sends their
roles and accessible names to an LLM. The model must respond through a typed
tool schema with one allowed action and one observed control ID. Code then
validates the decision against the expected semantic target before acting. A
successful trace is normalized into the reviewed artifact contract, rather
than persisting a model transcript. The loop is bounded by both step count and
wall-clock timeout. The trade-off is constrained discovery: it demonstrates a
real model deciding over a real live UI, but uses a known workflow grammar
instead of promising general autonomous browsing.

Everything is synchronous and single-process. That makes control flow and
failure semantics easy to inspect for a take-home. Production would put runs
behind durable jobs and isolate browser workers, but queues and distributed
infrastructure would not improve the load-bearing abstractions demonstrated
here.

# 2. Artifact schema

The JSON artifact is a versioned, strict Pydantic contract. Unknown fields are
rejected. It declares capability identity/version/approval, target app family
and compatible versions, parameterized routes and runtime bindings, typed
inputs and outputs with sensitivity policies, surface contexts, semantic
targets, ordered steps, runtime conditions, a success checkpoint, policy
requirements, and provenance.

Targets are defined once and referenced by ID. Each has a flow role
(`actionable` or `detectable`), an expected match range, ordered locator
strategies, a designated primary, fallback behavior, and a rationale. Locator
strategies are discriminated unions rather than bags of optional fields. This
is especially important for table relations: matching a row by a column value
and matching a key/value row by its label are different valid shapes, as are
selecting a descendant action and selecting a cell by column header. Invalid
combinations cannot validate.

`surface_contexts` are first-class resolvable objects instead of string frame
paths. A target points to a context ID, and the context has its own ordered
strategies and cardinality. One context override can therefore repair every
target inside a changed iframe, window, or desktop pane. That is both a cleaner
web model and the bridge to desktop automation.

Steps encode intent, typed action, risk, precondition, postcondition, timeout,
and retry policy. Wait and assert are not actions: waiting belongs to condition
evaluation and assertions are postconditions, avoiding two representations of
the same behavior. Detection-only targets allow zero or one match and treat
absence as a clean state; actionable targets must resolve uniquely. Artifact
validators enforce unique step and condition IDs, known context/target/route
references, the presence of each primary strategy, safe route policy
references, and that parser-produced fields are declared outputs.

The hand-authored artifact remains a permanent deterministic test fixture. A
discovery-generated artifact is stored separately under `capabilities/` and
copied into `evidence/`. The fixture is a reviewed contract; the generated file
is proof of the real run. Conflating them would make offline tests depend on
model behavior.

# 3. Determinism & error handling

Replay never asks a model what to do. It validates the invocation, intersects
the artifact with its embedded runtime policy, executes the fixed step order,
and evaluates explicit conditions. A browser test removes both
`ANTHROPIC_API_KEY` and `OPENROUTER_API_KEY` before successful replay to make
this boundary executable, not aspirational.

Target resolution tries the primary semantic strategy first—usually role plus
accessible name—then controlled fallbacks such as visible text, stable
attributes, or table relationships. A fallback success is returned as
`degraded`, making drift observable instead of silently normal. Row indexes and
generated CSS paths are avoided. Each locator must satisfy an explicit match
range, so ambiguous matches fail rather than clicking an arbitrary element.

Every action is bracketed by pre- and postconditions. Polling occurs inside a
bounded timeout and checks runtime conditions during the wait, which is where a
loading message actually exists. Retries are declared per step, limited, and
only repeat an action when it is marked idempotent. The whole run also has a
maximum runtime. A final checkpoint independently confirms both the correct
member and typed outputs.

The runtime taxonomy separates caller-meaningful business outcomes,
recoverable conditions, intervention requirements, and hard failures.
`MEMBER_NOT_FOUND` returns a structured business outcome, not an exception.
`TRANSIENT_LOADING` waits for a known transient indicator to disappear.
`SESSION_EXPIRED` raises an intervention request because credentials and MFA
are outside policy. Application errors stop with a typed failure. Successful
replay returns declared values; failure evidence can include a screenshot and
always omits invocation inputs. Structured evidence records each completed
step, its intent, action class, risk, and outcome. Financial outputs are
redacted while public currency metadata may be retained.

# 4. Heterogeneity & multi-tenant

The artifact describes semantic intent and control relationships; a surface
adapter translates them to a concrete technology. The implemented adapter uses
Playwright across legacy frames and table markup. A desktop adapter could map
the same accessibility strategy to an OS accessibility role/name, map a
surface context to a window or pane handle, and implement activate, enter text,
read, and press key through UI Automation or macOS Accessibility. A
screenshot/coordinate adapter could add an image-anchor strategy without
changing step execution, policy, runtime conditions, or result contracts.

For multi-tenant reuse, the capability should be owned at
`app_family + compatible_app_version` rather than copied per institution. A
base artifact would contain the common semantic targets and flow. Tenant and
version profiles would provide narrow, reviewable overrides for runtime origin,
route templates, context strategies, and target strategy ordering. Overrides
would be schema-validated and deep-merged only at named extension points; they
would not replace steps or widen policy silently.

Resolution telemetry provides the feedback loop. Primary success means the
base capability still fits. Repeated fallback/degraded resolutions can propose
a version or tenant override. Ambiguity or total failure quarantines unattended
execution and triggers review. Replay success rate, target-level strategy used,
vendor version, and checkpoint failures would be aggregated without PII. A
promoted override needs repeated successful replay and approval; it should not
be learned automatically from a single production failure.

# 5. Escalation & handoff

The artifact declares intervention conditions, priority, detection phases,
reason, transfer mode, and resume condition. Runtime monitoring detects an
expired-session marker while waiting or after a step and raises a typed
`InterventionRequired` event. The demo injects that same state and routes an
intervention containing capability, goal, current step, reason, session ID,
owner, and screenshot.

`HandoffSession` is an explicit lease with one owner: `automation` or `human`.
The handler pauses automation and changes ownership before prompting the local
operator. Crucially, it keeps the same Playwright `Page`, browser context,
cookies, and iframe alive. The human clicks Resume session in that browser and
signals completion. Understudy verifies the declared resume condition before
transferring ownership back; a signal alone is insufficient. An E2E test also
asserts object identity for the page and the two ownership transitions.

During human ownership, capturing listeners record click/input event type plus
semantic role/name across existing frames. They never record input values.
Before/after screenshots and the transfer ledger preserve evidence across the
seam. The operator surface is deliberately a terminal prompt plus headed
browser, not a co-browsing console. In production the same lease and events
would sit behind authenticated operator routing, expiry/heartbeat, and an
audited resume endpoint.

# 6. Safety

Policy is data in the artifact and is enforced before replay. It limits origins
and named routes, allowed action types, maximum steps/runtime, and risk classes.
The sample capability permits only read and reversible input actions;
irreversible actions require confirmation and therefore cannot run unattended.
Model decisions cannot supply URLs, selectors, code, or new target references.
Page content is explicitly treated as untrusted and cannot modify policy, which
contains prompt injection to observation data rather than instructions.

Inputs are validated against declared patterns. Routes interpolate only known
runtime bindings. Locators resolve only reviewed strategies during replay.
Discovery sends the supplied goal and visible control descriptions to the
configured provider but does not persist raw transcripts. Artifacts store
parameter references, never runtime values. Evidence replaces the member ID in
the goal, omits runtime inputs, redacts financial outputs and read values, and
does not capture credentials or tokens. The sample app must only use synthetic
data.

The current policy is embedded in each artifact, so a malicious artifact could
attempt to grant itself broader rights. Production must intersect it with a
separately administered tenant policy and enforce browser-network egress below
the application layer. Screenshot evidence can contain visible data; in a real
deployment it needs field masking, encrypted storage, access control, and a
retention policy. These are explicit limits, not assumed protections.

# 7. Cuts

I cut breadth rather than deleting a core capability. Discovery supports one
known banking workflow and two API providers; it is real but constrained. The
operator UI is a headed browser and terminal acknowledgement. Desktop and
screenshot surfaces, distributed workers, tenant override storage, artifact
signing, a capability catalog API, and production authentication are designed
at seams but not implemented. There is no open-ended LLM fallback during
replay, because that would weaken the central deterministic guarantee.

Next I would first add externally managed policy intersection and signed,
approved artifacts. Then I would add versioned tenant overrides plus resolution
telemetry and stability gates. For operations, I would add an authenticated
operator queue with expiring ownership leases and data-masked streaming. Only
after those controls would I broaden discovery, add a desktop accessibility
adapter, or consider a one-step, bounded, fully recorded model recovery path.
