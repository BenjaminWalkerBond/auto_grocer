# Status: <topic>

<!--
Shared status file for the auto_grocier multi-agent workflow. This is the single
source of truth passed between the Orchestrator and the Product Designer /
Developer / Tester subagents. Subagents run in isolated contexts and cannot see
each other, so ALL shared state lives here.

Rules:
- Every agent MUST read this file at the start of its turn.
- Every agent MUST update this file (including on failure) BEFORE returning.
- The Orchestrator owns creating this file (copy of this template) and updating
  routing fields (status, next_agent, attempt counters) between subagent calls.

Copy this template to .github/agents/handoffs/<slug>.md for each run.
-->

topic: <short slug>
chosen_idea: <one-line description of the idea being implemented>
status: READY_FOR_DEV   # READY_FOR_DEV | INFEASIBLE | READY_FOR_TEST | TESTS_FAILED | PASSED | ERROR | BLOCKED
next_agent: product-designer

## Attempt counters
design_attempts: 0
dev_attempts: 0
test_attempts: 0

## Design (Product Designer, Mode C)
goal:
non_goals:
scope_and_approach:
acceptance_criteria:
risks_and_dependencies:

## dev_plan (Developer — write BEFORE any code)
files_to_change:
approach:
feasibility:            # feasible | infeasible (+ reason)
risks:
verification:

## Implementation notes (Developer)
summary:
changed_files:

## test_plan (Tester — write BEFORE running anything)
commands:
criteria_mapping:       # which acceptance criterion each check covers
expected_outcomes:
prerequisites:          # venv active, HEB session valid, etc.

## Test results (Tester)
summary:
failures:               # test names + error output + context (when TESTS_FAILED)

## Feedback / handoff log
# Append a dated entry each time control changes hands: INFEASIBLE reasons,
# TESTS_FAILED details, ERROR / BLOCKED escalations.

## reason
# Populated on INFEASIBLE / ERROR / BLOCKED with a clear explanation.
