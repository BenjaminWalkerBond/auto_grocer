"""auto_grocier entrypoint.

The browser automation now runs on the async **nodriver** stack in the
``grocery_browser`` package (Selenium / undetected-chromedriver have been
removed). This module is a thin compatibility shim so ``python main.py`` keeps
working; it simply delegates to ``grocery_browser.run``.

The MODE is read from .env (or the MODE env var, which overrides). Modes:
    login_export, test, checkout_with_prompt, auto_checkout,
    graphql, graphql_checkout_with_prompt, graphql_auto_checkout,
    update_graphql_hashes

You can also run the package directly:
    python -m grocery_browser.run
    MODE=test python -m grocery_browser.run
"""
import nodriver

from session_maintenance.run import main as _run_main


if __name__ == "__main__":
    # nodriver ships its own event loop helper; asyncio.run is unreliable with it.
    nodriver.loop().run_until_complete(_run_main())
