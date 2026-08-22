# Showcase — MCP Server in the Chat Window

Shot list / outline for recording the **`auto-grocer` MCP server driving a real HEB
cart from your coding-agent chat** (GitHub Copilot Agent mode / Claude Desktop). The
whole stack runs in Docker (Postgres + MCP + headless Chromium); you just talk to it.

> No paid order is placed. The demo stops at `checkout` (review only). `place_order`
> is guarded/disabled — do not call it on camera.

---

## 0. Pre-roll setup (do BEFORE hitting record)

- [ ] Docker Desktop running; MCP image built
      (`docker compose -f docker/docker-compose.yml build mcp`).
- [ ] `.vscode/mcp.json` present so Copilot auto-detects `auto-grocer`.
- [ ] `.env` filled in (HEB creds, Gmail IMAP app password, `CLAUDE_API_KEY`,
      `DATABASE_PASSWORD`).
- [ ] A **valid HEB session already seeded** (do a warm-up so the demo doesn't stall
      on a live login / verification email).
- [ ] Chat panel open in Agent mode; tool-call output visible.
- [ ] Recorder framed on the chat window (tool calls + results readable).

---

## 1. Hook (0:00–0:15)

- [ ] On screen: chat panel, `auto-grocer` shown as a connected MCP server.
- [ ] Talking point: "No script, no clicking — I just *ask* my agent to shop my HEB
      cart. It calls MCP tools that drive HEB over GraphQL."

## 2. Session check (0:15–0:35)

- [ ] Type: **"Check my HEB session status."**
- [ ] Expect tool call: `auth_status` → `authenticated: true`.
- [ ] Talking point: "Every workflow starts here. If it were false, a login-refresh
      skill runs automatically inside the container."

## 3. Add groceries by natural language (0:35–1:15)

- [ ] Type: **"Add taco night ingredients to my cart — ground beef, tortillas,
      shredded cheese, salsa, and an avocado."**
- [ ] Expect tool call: `add_groceries` (or `add_recipe_ingredients`).
- [ ] Watch matched HEB products + quantities stream back.
- [ ] Talking point: "Free-form text → real HEB SKUs, matched server-side."

## 4. Add a recipe (1:15–2:00)

- [ ] Type: **"Add the ingredients for salmon gnocchi to my cart."**
- [ ] Expect tool call: `add_recipe_ingredients` (recipe matched from the DB) — or
      `find_recipes` first to preview.
- [ ] Talking point: "Recipes live in Postgres; it matches the recipe and adds each
      ingredient." (Optional: mention seeding a recipe from a URL/YouTube.)

## 5. Review the cart (2:00–2:30)

- [ ] Type: **"Show me my cart."**
- [ ] Expect tool call: `get_cart` → itemized list + subtotal.
- [ ] Talking point: "Full transparency before anything is reserved."
- [ ] (Optional) **"Remove the avocado."** → `remove_from_cart`.

## 6. Coupons (optional, 2:30–3:00)

- [ ] Type: **"Any coupons I can clip for what's in my cart?"**
- [ ] Expect tool calls: `list_coupons` → `clip_coupon`.
- [ ] Talking point: "It can clip digital coupons before checkout."

## 7. Reserve a pickup slot (3:00–3:40)

- [ ] Type: **"What pickup times are available? Reserve the earliest one."**
- [ ] Expect tool calls: `list_timeslots` → `reserve_timeslot`.
- [ ] Show the reserved slot echoed back.

## 8. Checkout — review only (3:40–4:20)

- [ ] Type: **"Take me to checkout so I can review the order."**
- [ ] Expect tool call: `checkout` → order review summary.
- [ ] Talking point (emphasize): "This is **review only — no card is charged**.
      Placing the paid order is a separate, guarded tool that's disabled by default."

## 9. Safety + how it works (4:20–4:50)

- [ ] Talking point: "`place_order` is the only tool that charges, and it's guarded —
      it won't fire from a casual prompt."
- [ ] Quick architecture beat: "Under the hood — Docker runs Postgres + the MCP server;
      cart ops go over HEB's GraphQL API; a headless Chromium (Xvfb) only wakes up to
      refresh the login session when needed."

## 10. Close (4:50–5:00)

- [ ] Talking point: "From 'add taco ingredients' to a reserved pickup slot — all from
      chat. Groceries, hands-free."
- [ ] End card / repo link.

---

## Exact prompts (copy/paste cheat sheet)

1. `Check my HEB session status.`
2. `Add taco night ingredients to my cart — ground beef, tortillas, shredded cheese, salsa, and an avocado.`
3. `Add the ingredients for salmon gnocchi to my cart.`
4. `Show me my cart.`
5. `Remove the avocado.`  *(optional)*
6. `Any coupons I can clip for what's in my cart?`  *(optional)*
7. `What pickup times are available? Reserve the earliest one.`
8. `Take me to checkout so I can review the order.`
 
## Tool-call map (what viewers should see fire)

| Prompt | Tool(s) |
|--------|---------|
| Session check | `auth_status` |
| Add groceries | `add_groceries` / `add_recipe_ingredients` |
| Add recipe | `find_recipes`, `add_recipe_ingredients` |
| Review cart | `get_cart`, `remove_from_cart` |
| Coupons | `list_coupons`, `clip_coupon` |
| Timeslot | `list_timeslots`, `reserve_timeslot` |
| Checkout | `checkout` |
| (never on camera) | `place_order` — charges card, keep disabled |

## Gotchas to avoid on camera

- [ ] Warm up the session first — a live login/verification mid-demo kills pacing.
- [ ] Don't reveal `.env` creds or the chat's raw auth output.
- [ ] Never call `place_order`.
- [ ] If a tool returns `NOT_AUTHENTICATED` / `OPERATION_NOT_CAPTURED`, cut — run the
      refresh skills off-camera, then resume.
