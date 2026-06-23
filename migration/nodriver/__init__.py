"""Async nodriver implementation of the auto_grocier browser layer (Step 1 prototype).

Modules:
    browser       - start/stop a nodriver Browser with auto-detected Chrome.
    primitives    - async helpers (delays, typing, select-with-fallbacks, modals).
    logger        - async screenshot/HTML/error capture into debug_logs/.
    auth_export   - export the live session (cookies + localStorage) to auth.json.
    self_healing  - async-aware Claude-powered function repair.
    flows         - login, clear_cart, reserve_time_slot, change_store_via_ui,
                    add_ingredient, checkout (all async).
    hash_capture  - capture GraphQL persisted-query hashes via CDP Network events.
    run           - async mode dispatcher mirroring main.py's MODES.

Nothing here imports Selenium or undetected_chromedriver.
"""
