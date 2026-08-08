# Changelog

All notable changes to auto_grocier are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Pre-1.0.0 releases may change interfaces between minor versions.

## [Unreleased]

### Changed

- **Dependency management migrated to [uv](https://docs.astral.sh/uv/).**
  `pyproject.toml` (with static `[project.dependencies]` + a `dev`
  `[dependency-groups]`) and a committed, hash-pinned `uv.lock` are now the single
  source of truth. `requirements.txt` / `requirements-dev.txt` were removed, and
  Docker, CI, and the docs now install via `uv sync --frozen` / run via `uv run`.
  Same dependency set and version constraints — packaging change only. Also fixed
  `.python-version` (`3.10.12` → `3.12`) to match `requires-python`.

## [0.1.0] - 2026-07-31

Initial public release. auto_grocier automates H-E-B grocery ordering through an
[MCP](https://modelcontextprotocol.io/) server that replays H-E-B's GraphQL
persisted-query API using an exported browser session, backed by a PostgreSQL
recipe database.

> **Disclaimer:** auto_grocier is not affiliated with, endorsed by, or sponsored
> by H-E-B, and is provided for personal and educational use only. See the
> [Disclaimer](README.md#disclaimer) and [Credits](README.md#credits) in the README.

### Added

- **MCP server** (`mcp_server.py`, `FastMCP(name="auto-grocier")`) exposing H-E-B
  grocery automation over pure GraphQL — product search, cart management
  (`add_groceries`, `get_cart`, `clear_cart`, `remove_from_cart`), recipe
  ingredient adding (`add_recipe_ingredients`, `find_recipes`), timeslot
  reservation, coupons, store selection, and a review-only `checkout`. The
  card-charging `place_order` is disabled by default.
- **Recipe database** — PostgreSQL schema with recipe, ingredient, and tag
  repositories, seeding and tagging utilities, and natural-language recipe
  matching.
- **Session maintenance** (`session_maintenance/`) — an async
  [nodriver](https://github.com/ultrafunkamsterdam/nodriver) browser flow that
  logs into H-E-B (handling email verification), exports the session, and
  captures the GraphQL persisted-query hashes the MCP server replays.
- **Dockerized stack** (`docker/docker-compose.yml`, `docker/Dockerfile.mcp`) —
  PostgreSQL plus the MCP server with bundled Chromium and Xvfb, so the container
  can refresh its own H-E-B session. Postgres data persists in the
  `auto_grocier_pgdata` volume; the exported session persists in
  `auto_grocier_session`.
- **Licensing and attribution** — root MIT `LICENSE`, a `NOTICE` file, and README
  Credits crediting the upstream project
  [texas-grocery-mcp](https://github.com/mgwalkerjr95/texas-grocery-mcp) by
  Michael Walker (MIT), whose MCP server design this project builds on.
- **Continuous integration** — GitHub Actions workflows running `ruff` lint and
  the full `pytest` unit suite on every push and pull request (gating), an
  advisory `mypy` type-check job, and a scoped Docker image build check on the
  `main` branch.
- **Secret-scanning guard** — `.gitleaks.toml` and a `.pre-commit-config.yaml`
  gitleaks hook.

### Changed

- **Renamed the vendored package** `texas_grocery_mcp` → `auto_grocier_mcp` so the
  project no longer ships under the upstream author's project name. The upstream
  MIT license and attribution are preserved (see `NOTICE` and
  `auto_grocier_mcp/LICENSE`); on-disk runtime names (the `~/.texas-grocery-mcp/`
  session directory, the OS keyring service name, and the Docker volume mounts)
  are intentionally unchanged to avoid orphaning existing sessions.
- **Cross-platform documentation** — the README Quick Start now creates a fresh
  virtual environment with both PowerShell and bash instructions, adds a
  Prerequisites section covering every requirement (Docker, PostgreSQL, Chromium,
  a Gmail app password, an Anthropic API key, an H-E-B account, and store
  selection), and leads with the recommended Docker path.
- **Single dependency source of truth** — runtime dependencies live only in
  `requirements.txt` (consumed by `pyproject.toml` and the Docker image);
  development dependencies live in `requirements-dev.txt`.
- **CI now lints all first-party code** (`ruff check .`) and runs the full unit
  suite, replacing the previous narrow lint scope.

### Fixed

- **`add_recipe_ingredients` MCP tool was not registered** — its `@mcp.tool()`
  decorator and function signature had been dropped by a prior edit, leaving the
  body as unreachable dead code even though the tool is documented throughout.
  Restored so the tool registers and works.
- **`scripts/apply_updates.py` read the wrong directory** — it looked in
  `grocery_browser/updated_functions/` while self-healing writes rewrites to
  `session_maintenance/updated_functions/`, so it never found anything. Repointed
  to the correct location.
- **Windows-only test failures** — the `0o600` secure-file-permission tests now
  skip on Windows (which cannot enforce POSIX file modes) while still running and
  enforcing the assertion on Linux/macOS, where the Docker image runs.
- **Cleared 286 lint errors** across first-party code, including undefined-name
  (`F821`) issues, and de-duplicated documentation.

### Security

- **Removed personal PII and secrets from the working tree** — deleted captured
  H-E-B page dumps under `debug_logs/` that contained account details and order
  history, and tightened `.gitignore` so such artifacts are never tracked. Git
  history was verified clean (no secret or PII was ever committed), so no history
  rewrite or credential rotation was required.
- **Removed the weak default database password** from `docker/docker-compose.yml`
  in favor of a fail-fast required `DATABASE_PASSWORD` variable.
- **Added legal framing** — a README disclaimer clarifying no H-E-B affiliation, a
  trademark notice, a personal/educational-use limitation, and a no-warranty
  statement.

[Unreleased]: https://github.com/BenjaminWalkerBond/auto_grocier/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/BenjaminWalkerBond/auto_grocier/releases/tag/v0.1.0
