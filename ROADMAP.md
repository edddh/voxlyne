# Roadmap

## 1. Reproducible Demo Installation

**Deliverable:** a one-command local bootstrap and Docker Compose profile for
a safe demo environment.

- Add `make demo-up`, `make demo-reset`, and `make demo-check` targets.
- Run migrations, create Demo Showcase, and expose a health report without
  credentials or external voice providers.
- Add a CI job that starts the stack, seeds synthetic data, and calls health
  and list endpoints.

**Done when:** a new contributor can clone the repository and obtain a working
demo UI with four fictional scenarios in under 15 minutes.

## 2. Simulation Regression Suite

**Deliverable:** saved, replayable voice-agent test cases.

- Define JSON fixtures for standard reception, recruiting, retail, and
  restaurant scenarios.
- Run each fixture against a prompt version and record response, tool calls,
  latency, and estimated cost.
- Add pass/fail assertions for required tool use, prohibited promises, chosen
  language, and maximum response length.
- Show a prompt-version comparison in the project editor before publishing.

**Done when:** a prompt change cannot be published without seeing its result
against the scenario regression set.

## 3. Controlled External Actions

**Deliverable:** an action gateway for calendar, CRM, and ticketing adapters.

- Define typed input/output schemas for every external action.
- Require idempotency keys and structured success/failure responses.
- Add `dry_run`, `approval_required`, and `disabled` execution modes.
- Persist an audit record with request, redacted result, actor, and replay ID.

**Done when:** a simulated call can demonstrate an appointment or ticket flow
without contacting an external system, while production adapters remain
explicitly opt-in.

## 4. Specialist-Agent Handoffs

**Deliverable:** routing that transfers structured context to another agent or
a human operator.

- Add handoff rules based on intent, confidence, and tool outcome.
- Pass a bounded summary rather than the complete transcript.
- Add a human-review queue with accept, reject, and callback outcomes.
- Measure containment rate, handoff rate, and unresolved requests.

**Done when:** the standard demo can route scheduling requests to a scheduling
agent and sensitive requests to a human-review queue.

## 5. Retrieval Evaluation and Traceability

**Deliverable:** reliable, inspectable knowledge-base answers.

- Record the source chunks returned for each retrieval tool call.
- Add a small question-and-answer evaluation set per demo scenario.
- Flag answers with no source, low retrieval score, or conflicting chunks.
- Add a UI view that links an answer to the exact indexed source excerpts.

**Done when:** each demo answer based on retrieval can be inspected and
reproduced from its source chunks.

## 6. Accessibility and Release Discipline

**Deliverable:** a release checklist enforced by automation.

- Add keyboard and screen-reader checks for login, projects, calls, and
  simulator flows.
- Add visual snapshots for desktop and mobile critical screens.
- Publish a changelog and migration notes for every release.
- Add dependency and secret scans to CI.

**Done when:** `main` is releasable only after tests, scans, and the demo
smoke check pass.
