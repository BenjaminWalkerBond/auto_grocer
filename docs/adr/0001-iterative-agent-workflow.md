# ADR 0001: Iterative Multi-Agent Development Workflow

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** Repository owner

## Context

We want to automate iterative improvements to `auto_grocer` (an HEB grocery-automation
MCP server with a recipe database and GraphQL cart control) with clear role separation
between product design, implementation, and testing.

VS Code custom agents (`.agent.md`) are available. Important platform facts that shape the
design:

- Subagents run in an **isolated context** and return a **single message**; there is no
  shared memory between subagents.
- There are two distinct coordination mechanisms: **subagents** (`agents:` frontmatter +
  the `agent` tool, invoked programmatically) and **handoffs** (`handoffs:` frontmatter,
  which render user-driven buttons). They are not interchangeable.
- Today a subagent that errors out simply stops, with no recovery path for the caller.

## Decision

1. **Four workspace agents** in `.github/agents/`: `product-designer`, `developer`,
   `tester`, and `orchestrator`.
2. **Hub-and-spoke orchestration.** The orchestrator is the sole router and invokes the
   workers as **subagents** (the `agent` tool). Workers set `agents: []` so they cannot
   invoke each other. **No `handoffs:`** are used anywhere — orchestration is 100%
   subagent-driven.
3. **Three communication channels** (subagents are isolated, so state must be explicit):
   - A shared **status file** at `.github/agents/handoffs/<topic>.md` acts as the durable
     message bus. Every agent reads it at the start of its turn and writes its outcome
     (including on failure) before returning.
   - The **orchestrator → subagent prompt** carries a focused brief plus the status file
     path.
   - The **subagent → orchestrator return message** is a single summary; the orchestrator
     re-reads the file for the authoritative state.
4. **User-gated entry.**
   - *Phase 0 — Ideation:* the user asks the orchestrator either for open-ended top ideas
     or to implement a specific idea. The orchestrator runs the product designer, presents
     the proposals, and **stops**.
   - *Phase 1 — Confirm:* the user picks and explicitly confirms.
   - *Phase 2 — Automated loop:* only runs after explicit confirmation.
5. **Plan-first workers.** The developer writes a `dev_plan` (with a feasibility gate)
   before writing any code; the tester writes a `test_plan` before running anything. Both
   are recorded in the status file.
6. **Feedback via orchestrator re-invocation.** `developer` ↔ `product-designer` on
   `INFEASIBLE`; `tester` ↔ `developer` on `TESTS_FAILED`.
7. **Resilience.** A `status:` enum
   (`READY_FOR_DEV`, `INFEASIBLE`, `READY_FOR_TEST`, `TESTS_FAILED`, `PASSED`, `ERROR`,
   `BLOCKED`); write-before-return; trust the file, not the message; a maximum of 3
   attempts per stage tracked by counters; a progress guard against ping-pong; a
   `SubagentStop` hook that injects an `ERROR` record if a subagent stops without updating
   the status file; and `BLOCKED` escalation to the user.
8. **Models pinned as fallback arrays** (first available is used):
   - Product Designer: `Claude Opus 4.8 High thinking 1M` (+ fallbacks)
   - Developer: `Claude Opus 4.8 Medium thinking 1M` (+ fallbacks)
   - Tester: `Claude Sonnet 4.6` (+ fallbacks)
   - Orchestrator: `Claude Opus 4.8 Low thinking 1M` (+ fallbacks)
9. **Tester is fully automated with full access** and runs `pytest -ra`,
   `pytest --run-integration`, `ruff check`, and `python main.py` with `MODE=test`.

## Consequences

**Positive**
- State is reviewable and durable; the loop survives subagent crashes.
- The human stays in control at kickoff and at any `BLOCKED` escalation.
- Each role has least-privilege tools.

**Negative / risks**
- Status-file discipline is load-bearing — an agent that forgets to update the file relies
  on the `SubagentStop` hook backstop.
- Integration tests and the `MODE=test` run can hit live HEB, which risks WAF 401s and
  auth challenges. Harness/environment failures are surfaced as `BLOCKED` (with a pointer
  to the `refresh-heb-login` / `refresh-graphql-hashes` skills) rather than retried
  against heb.com.

## Alternatives considered

- **Peer handoffs between agents** — rejected: the orchestrator loses control and it invites
  circular handoffs.
- **Message-only communication (no shared file)** — rejected: subagents are isolated, so
  there would be no durable state to hand off.
- **Manual stepping via handoff buttons** — rejected: the desired flow is an automated loop
  that runs after a single user confirmation.
