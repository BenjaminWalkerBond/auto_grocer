"""auto_grocer test suite.

Layout
------
This top-level ``tests/`` package holds shared pytest configuration and the two
test categories (split by speed + dependencies):

* ``tests/conftest.py`` - shared fixtures, the ``integration`` marker, and the
  ``--run-integration`` command-line flag that gates the split below.
* ``tests/unit/``        - fast, ISOLATED tests. Everything external (HEB API,
  network, session) is mocked, so they need no credentials and run on every CI
  push. Our own logic (e.g. ``test_graphql_cart.py``) lives here.
* ``tests/integration/`` - tests that hit the REAL HEB API / need a live
  session. Skipped by default; run with ``pytest --run-integration``.

So ``tests/`` is the umbrella; ``unit`` and ``integration`` are the two tiers.
"""
