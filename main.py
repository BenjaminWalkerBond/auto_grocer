"""auto_grocier entrypoint.

The browser automation now runs on the async **nodriver** stack in the
``session_maintenance`` package (Selenium / undetected-chromedriver have been
removed). This module is a thin compatibility shim so ``python main.py`` keeps
working; it simply delegates to ``session_maintenance.run``.

The MODE is read from .env (or the MODE env var, which overrides). Two core modes:
    graphql   - shop via the HEB GraphQL API. CHECKOUT=none|prompt|auto.
    nodriver  - drive the browser. OPERATION=shop|login_export|capture_hashes;
                for OPERATION=shop, CHECKOUT=none|prompt|auto.

You can also run the package directly:
    python -m session_maintenance.run
    MODE=nodriver OPERATION=shop python -m session_maintenance.run
"""
import nodriver

from session_maintenance.run import main as _run_main

if __name__ == "__main__":
    # nodriver ships its own event loop helper; asyncio.run is unreliable with it.
    nodriver.loop().run_until_complete(_run_main())
