# AGENTS.md — working agreements for AI agents in this repo

This file captures hard rules and conventions for any AI agent working in
`auto_grocer`. Read it before running commands or making changes. It complements
[.github/copilot-instructions.md](.github/copilot-instructions.md) and
[CLAUDE.md](CLAUDE.md) (MCP usage, session/hash refresh skills).

## Terminal output — DO NOT hide logs

**Never pipe a command's output through `tail`, `head`, `grep`, `wc`, or similar
truncating filters when you need to understand what happened.** You must be able
to see the full logs to make correct decisions. Truncating output has repeatedly
caused wrong conclusions in this repo (a stale session, a failed browser capture,
a WAF block, or a stack trace is exactly the thing that scrolls off when you
`| tail`).

Rules:
- Run commands so their **complete stdout/stderr is visible**. No `| tail -N`,
  `| head`, `2>&1 | grep ...` on diagnostic/build/test/capture runs.
- If output is genuinely huge, redirect it to a file and then READ the file
  (e.g. `... > /tmp/run.log 2>&1` then open `/tmp/run.log`) — do not filter it
  away inline.
- This applies especially to: `docker compose ... run` (MCP server, browser
  capture), `session_maintenance.run` (login / capture_hashes), `main.py`,
  `pytest`, and anything that drives the browser or hits HEB.
- `docker compose` interpolates the whole file, so always pass `--env-file .env`
  (or run from the repo root) or `DATABASE_PASSWORD` interpolation fails.
- Filtering unrelated, already-understood output (e.g. `docker ps | grep mcp`)
  is fine. The rule is about not blinding yourself to logs you need to reason
  about.

## Never truncate session-maintenance output

A stale session or stale GraphQL hashes means session maintenance itself is
suspect — so its output is the most important thing to see. Run
`auto_grocer.session_maintenance.run` (login / capture_hashes) with its **full
output**, never piped to a filter. See
[.github/copilot-instructions.md](.github/copilot-instructions.md) for the exact
Docker invocation.

## Verify with evidence

Before claiming something works, run the real command and read its full output.
Prefer running the actual failing path over asserting a fix is correct.
