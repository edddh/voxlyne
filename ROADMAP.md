# Roadmap

## Product Direction: Open-Source AI Telephony

Voxlyne is intended to evolve into a robust, self-hosted AI telephony platform.
It should let developers connect a phone number, select an external voice/LLM
provider, configure an agent, test it safely, and inspect every call and tool
execution from one open-source control plane.

The goal is reliable telephone automation with explicit boundaries. Routine
requests can be automated; exceptions, ambiguous requests, sensitive data, and
high-impact actions remain policy-governed and transferable to a person.

## 1. Reproducible Demo Installation

**Deliverable:** a one-command bootstrap and Docker Compose profile for a safe
demo environment.

- Add `make demo-up`, `make demo-reset`, and `make demo-check` targets.
- Run migrations, create Demo Showcase, and expose a health report without
  credentials or external providers.
- Add CI that starts the stack, seeds synthetic data, and calls health and
  list endpoints.

**Done when:** a new contributor can obtain a working demo UI with four
fictional scenarios in under 15 minutes.

## 2. Business Context Graph

**Deliverable:** one durable case record that joins every interaction and
business object involved in a request.

- Model callers, organizations, contacts, orders, appointments, tickets,
  documents, and conversations as linked entities.
- Build a case timeline that merges calls, messages, tool executions, agent
  handoffs, and human decisions.
- Add identity resolution with confidence and explicit conflict handling
  instead of assuming one phone number equals one person.
- Expose a read-only context API used by all agents and channels.

**Done when:** an agent can resume a request from another channel with the
relevant history, open tasks, and source-system references already available.

## 3. Enterprise Action Catalog

**Deliverable:** a policy-controlled catalog of actions over calendars, CRM,
ticketing, commerce, billing, document, and internal systems.

- Define typed input/output schemas and idempotency keys for every action.
- Add adapters for calendar availability, CRM lookup/update, ticket creation,
  order status, document retrieval, and outbound notifications.
- Add `dry_run`, `approval_required`, `automatic`, and `disabled` modes per
  tenant, project, action, and risk level.
- Persist an audit record with actor, policy decision, redacted request,
  result, source-system ID, and replay ID.

**Done when:** a demo agent can resolve an appointment, support, or recruiting
case end-to-end against mocked business systems without free-form API access.

## 4. Specialist-Agent Orchestration

**Deliverable:** an orchestrator that delegates bounded tasks to specialist
agents instead of one generalist model attempting every task.

- Introduce agent roles for triage, retrieval, scheduling, CRM, document
  review, follow-up, and quality assurance.
- Define explicit handoff contracts: case summary, required inputs, allowed
  actions, expected output, timeout, and escalation rule.
- Add a planner that chooses the next specialist only from policy-approved
  options and records the rationale.
- Add a human handoff queue with accept, reject, callback, and resume states.

**Done when:** an appointment-scheduling demo can route scheduling to a scheduling
agent, missing information to a follow-up agent, and sensitive requests to a
human queue while preserving one case timeline.

## 5. Omnichannel Case Continuity

**Deliverable:** one case can move between phone, web chat, email, messaging,
and a human operator without restarting the conversation.

- Normalize channel events into the case timeline.
- Add channel-specific consent, identity, and notification policies.
- Let a caller receive a secure link or follow-up message that continues an
  unfinished case.
- Add outbound follow-up only when a policy and explicit user preference allow
  it.

**Done when:** a synthetic caller can begin by phone, receive a follow-up, and
complete the same request in web chat without repeating the context.

## 6. Simulation, Evaluation, and Digital Twin

**Deliverable:** a safe environment that proves an agent workflow before it
can touch a production integration.

- Define replayable fixtures for appointment scheduling, recruiting, retail, and
  restaurant scenarios.
- Provide mocked versions of every external system with deterministic data.
- Record response, tool calls, policy decisions, latency, cost, and final case
  outcome for each run.
- Compare prompt, policy, model, and tool changes against a regression suite.
- Add adversarial cases: ambiguous identity, unavailable slot, duplicate
  request, conflicting knowledge, and forbidden action.

**Done when:** a change cannot enable automatic external actions until it has
passed the relevant synthetic workflow and policy tests.

## 7. Retrieval Traceability and Operational Trust

**Deliverable:** every factual answer and every action is inspectable.

- Store source chunks and scores for each retrieval-backed answer.
- Flag unsupported answers, conflicting sources, low confidence, and stale
  knowledge.
- Add a supervisor view with case state, agent path, tool results, policy
  decisions, and unresolved blockers.
- Provide a "why did it do this?" explanation assembled from structured
  execution records, not model self-reporting alone.

**Done when:** an operator can reconstruct the exact evidence and policy that
led to any answer, handoff, or external action.

## 8. Release and Safety Gate

**Deliverable:** automation that blocks unsafe releases.

- Run dependency, secret, schema, and migration checks in CI.
- Run demo smoke tests plus workflow regression tests before release.
- Require explicit approval for policy changes that increase autonomous action
  scope.
- Produce changelog, migration notes, and rollback steps for every release.

**Done when:** `main` cannot be released until code, synthetic workflows, and
action-policy checks all pass.
