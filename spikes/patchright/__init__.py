"""Patchright stealth spike for HEB.

Benchmarks whether ``patchright`` (a patched, undetected drop-in for Playwright)
can clear HEB's Imperva/Incapsula WAF on a **headless-under-Xvfb cold login** and
produce a valid ``reese84`` token + fresh GraphQL persisted-query hashes — the
capabilities the project currently relies on ``nodriver`` for.

This package is intentionally isolated from ``auto_grocer.session_maintenance``:
it reuses the project's *pure* helpers (settings, email OTP, reese84 validation,
hash parsing/saving) but drives the browser through patchright's Playwright API.
Nothing here is imported by the shipped MCP server or the nodriver flow.

Run it with the ``run_spike`` module — see that file's docstring.
"""
