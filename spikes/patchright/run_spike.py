"""Benchmark patchright against HEB's Imperva WAF (cold-login stealth spike).

Runs a full HEB **cold login** through patchright N times and reports how often
it (a) completed login, (b) produced a *valid* ``reese84`` token, and (optionally)
(c) captured fresh GraphQL persisted-query hashes — the exact capabilities the
project relies on ``nodriver`` for today. This is the empirical test of whether
patchright clears Imperva (its README lists Cloudflare/Kasada/Akamai/DataDome but
NOT Imperva by name), so we measure rather than assume.

Prerequisites (one-time):

    uv sync --extra spike            # installs patchright
    uv run patchright install chromium   # or: ... install chrome  (best stealth)

Run (from the repo root):

    # Single headed-under-Xvfb cold login + validation (recommended first run):
    uv run python -m spikes.patchright.run_spike --runs 1

    # Measure Imperva pass-rate over several spaced-out logins + hash capture:
    uv run python -m spikes.patchright.run_spike --runs 5 --capture --delay 90

    # Force true headless (more detectable; expected to fail more often):
    AUTO_GROCER_HEADLESS=1 uv run python -m spikes.patchright.run_spike --runs 3

In Docker (matches the nodriver image: headed under Xvfb, no sandbox):

    docker compose --env-file .env -f docker/docker-compose.yml run --rm -T \
      -e AUTO_GROCER_NO_SANDBOX=1 mcp \
      python -m spikes.patchright.run_spike --runs 5 --capture --delay 90

NOTE: HEB rate-limits aggressively. Keep ``--delay`` generous (>=60s) so repeated
cold logins don't trip the WAF and skew the result.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

try:
    from patchright.async_api import async_playwright
except ImportError:
    print(
        "patchright is not installed.\n"
        "  uv sync --extra spike\n"
        "  uv run patchright install chromium",
        file=sys.stderr,
    )
    sys.exit(2)

from auto_grocer.utility.graphql_auth import DEFAULT_AUTH_PATH
from spikes.patchright import browser, flow


async def _one_run(
    run_no: int,
    *,
    capture: bool,
    headless: bool | None,
    auth_path: str | None,
    save_hashes: bool = False,
) -> dict:
    result: dict = {"run": run_no}
    async with async_playwright() as p:
        context, page = await browser.start_context(p, headless=headless)
        operations = flow.attach_hash_capturer(context) if capture else {}
        try:
            login_status = await flow.login(page)
            result["login"] = login_status
            if capture and login_status.get("ok"):
                await flow.exercise_for_hashes(page)
                result["hashes_captured"] = sum(
                    1 for o in operations.values() if o.get("hash")
                )
                result["target_hits"] = flow.target_hits(operations)
                if save_hashes:
                    base = Path(auth_path).parent if auth_path else DEFAULT_AUTH_PATH.parent
                    hp, sp = flow.save_captured(
                        operations,
                        hashes_path=base / "persisted_queries.patchright_spike.json",
                        samples_path=base / "captured_operations.patchright_spike.json",
                    )
                    result["hashes_path"] = str(hp) if hp else None
            result["session"] = await flow.export_and_validate(context, auth_path)
        finally:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
    return result


def _summarise(results: list[dict]) -> None:
    n = len(results)
    logins = sum(1 for r in results if r.get("login", {}).get("ok"))
    authed = sum(1 for r in results if r.get("session", {}).get("authenticated"))
    reese_ok = sum(1 for r in results if r.get("session", {}).get("reese84", {}).get("valid"))

    print("\n" + "=" * 60)
    print("PATCHRIGHT vs IMPERVA — SPIKE RESULTS")
    print("=" * 60)
    for r in results:
        login = r.get("login", {})
        sess = r.get("session", {})
        reese = sess.get("reese84", {})
        line = (
            f"  run {r['run']}: login={'ok' if login.get('ok') else 'FAIL'}"
            f"({login.get('stage')}/{login.get('verify', '-')}) "
            f"authed={sess.get('authenticated')} "
            f"reese84={reese.get('reason')}"
        )
        if "hashes_captured" in r:
            line += f" hashes={r['hashes_captured']} targets={len(r.get('target_hits', []))}"
        print(line)

    print("-" * 60)
    print(f"  logins ok:      {logins}/{n}")
    print(f"  authed cookies: {authed}/{n}")
    print(f"  reese84 valid:  {reese_ok}/{n}   <-- Imperva pass-rate")
    print("=" * 60 + "\n")


async def _main(args) -> int:
    headless = True if args.headless else (False if args.headed else None)
    results: list[dict] = []
    for i in range(1, args.runs + 1):
        print(f"\n▶ Run {i}/{args.runs} ...")
        try:
            results.append(
                await _one_run(
                    i,
                    capture=args.capture,
                    headless=headless,
                    auth_path=args.auth_out,
                    save_hashes=args.save_hashes,
                )
            )
        except Exception as e:  # noqa: BLE001 - keep the benchmark going
            print(f"  run {i} crashed: {type(e).__name__}: {e}", file=sys.stderr)
            results.append({"run": i, "login": {"ok": False, "stage": "crash", "detail": str(e)}})
        if i < args.runs and args.delay:
            print(f"  ⏳ waiting {args.delay}s before next run (avoid WAF rate-limit)...")
            await asyncio.sleep(args.delay)

    _summarise(results)
    return 0 if any(r.get("session", {}).get("reese84", {}).get("valid") for r in results) else 1


def cli() -> int:
    parser = argparse.ArgumentParser(description="Patchright HEB Imperva cold-login spike.")
    parser.add_argument("--runs", type=int, default=1, help="Number of cold-login attempts.")
    parser.add_argument("--capture", action="store_true", help="Also capture GraphQL hashes.")
    parser.add_argument("--delay", type=int, default=90, help="Seconds between runs (default 90).")
    parser.add_argument("--headed", action="store_true", help="Force headed (default under Xvfb).")
    parser.add_argument("--headless", action="store_true", help="Force true headless.")
    parser.add_argument("--auth-out", default=None, help="Override auth.json output path.")
    parser.add_argument(
        "--save-hashes",
        action="store_true",
        help="Write captured hashes to *.patchright_spike.json (never the production files).",
    )
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(cli())
