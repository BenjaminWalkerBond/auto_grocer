"""Unit tests: fast, isolated, fully mocked.

No network, no HEB session, no credentials required. These run on every CI push
(``pytest tests/unit``). If a test needs the real HEB API, it belongs in
``tests/integration`` instead.
"""
