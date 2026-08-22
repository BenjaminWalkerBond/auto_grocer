# Showcase — Local Dev in a Real Browser (nodriver mode)

Shot list / outline for recording the **local development mode**, where
`auto_grocer` drives a **real, visible Chromium window on your own desktop** and
shops heb.com end-to-end. This is the "watch the automation work" demo — no
Docker, no Xvfb, the browser is right there on screen.

> No paid order is placed. `CHECKOUT=none` only adds to cart; checkout (if shown)
> stops at HEB's review page.

---

## 0. Pre-roll setup (do BEFORE hitting record)

- [ ] `.env` filled in: `EMAIL`, `PASSWORD` (HEB), Gmail IMAP app password,
      `CLAUDE_API_KEY`, store set.
- [ ] Set local-dev browser mode in `.env`:
  ```
  MODE=nodriver
  OPERATION=shop
  CHECKOUT=none
  INGREDIENT_SOURCE=hardcoded
  ```
- [ ] `uv sync` already run (env ready, no first-run install lag on camera).
- [ ] A clean-ish HEB cart (or let the run clear it — that's part of the demo).
- [ ] Screen recorder framed so the Chromium window + terminal are both visible.
- [ ] Terminal open at repo root.

---

## 1. Hook (0:00–0:15)

- [ ] On screen: the terminal + empty desktop.
- [ ] Talking point: "This is the automation running **locally in a real browser** —
      you can watch every click. Same code the Docker/MCP path runs headless."
- [ ] Show the `.env` mode block (`MODE=nodriver OPERATION=shop CHECKOUT=none`) and
      call out: "nodriver = drive the site, shop = add ingredients, none = no checkout."

## 2. Kick off the run (0:15–0:35)

- [ ] Run:
  ```bash
  uv run python main.py
  ```
- [ ] Talking point: "`main.py` is a thin shim → `session_maintenance.run`. It reads
      the mode from `.env`."
- [ ] Point at terminal: mode banner + "Using hardcoded ingredient list" (the sample
      **salmon gnocchi** recipe).

## 3. Browser launches + login (0:35–1:20)

- [ ] A real Chromium window pops open on the desktop.
- [ ] Narrate the auto-login: navigates to heb.com, enters credentials from `.env`.
- [ ] Show the email-verification handoff: "HEB emails a code — it's read over IMAP
      automatically, no manual copy/paste."
- [ ] Call out bot-protection challenge being handled like a normal browser session.
- [ ] Land on the logged-in HEB homepage.

## 4. Clear cart (1:20–1:40)

- [ ] Browser navigates to the cart and removes existing items.
- [ ] Talking point: "Starts from a clean slate so the demo is repeatable."

## 5. Reserve a pickup timeslot (1:40–2:10)

- [ ] Reservation modal opens; a free curbside date + timeslot is selected.
- [ ] Talking point: "It locks a pickup window before adding items — mirrors how a
      human shops."
- [ ] Note graceful handling: sold-out days are tolerated, it moves on.

## 6. Add ingredients live (2:10–3:30) — the money shot

- [ ] Terminal prints `🛒 Adding N ingredients to cart...` then each
      `Adding: <ingredient>`.
- [ ] Browser searches each item on heb.com and clicks **Add to cart** in sequence
      (olive oil, shallot, garlic, gnocchi, smoked salmon, cream cheese, spinach…).
- [ ] Call out the produce rule: vegetables/fruit get an "organic" prefix.
- [ ] Cart count ticks up in the header as each item lands.

## 7. Self-healing moment (optional, 3:30–4:10)

- [ ] Talking point: "If HEB changes a selector and a step breaks, `self_healing_call`
      sends a screenshot + page HTML to Claude, which rewrites the broken flow function
      on the fly (up to 3 retries)."
- [ ] Show `session_maintenance/updated_functions/` — "repaired functions land here for
      review/commit."
- [ ] (If you can't force a break live, just show the directory + explain.)

## 8. Wrap: inspect the cart (4:10–4:40)

- [ ] Run finishes; browser **stays open** on purpose.
- [ ] Manually scroll the cart to prove all ingredients are really there.
- [ ] Terminal shows the completion message ("press Enter to close the browser").
- [ ] Talking point: "No checkout, no charge — `CHECKOUT=none` stops here."
- [ ] Press Enter → browser closes.

## 9. Bridge to the MCP demo (4:40–5:00)

- [ ] Talking point: "That same shopping logic is exposed as MCP tools — so instead of
      running a script, I can just *ask my chat agent* to do it. Let's see that next."
- [ ] → cut to `SHOWCASE_MCP_CHAT.md`.

---

## B-roll / cutaways to grab

- [ ] Close-up of the `.env` mode block.
- [ ] Terminal scroll of the ingredient-add log.
- [ ] `session_maintenance/updated_functions/` folder contents.
- [ ] The salmon-gnocchi recipe list in `session_maintenance/run.py`
      (`HARDCODED_INGREDIENTS`).

## Gotchas to avoid on camera

- [ ] Don't show `.env` values (creds) — blur or pre-crop.
- [ ] First-ever run is slow (login + verification email); do a warm-up run first.
- [ ] If WAF/email verification stalls, cut and retry — don't hammer heb.com live.
- [ ] Keep `CHECKOUT=none` — never demo `place_order` on a live account.
