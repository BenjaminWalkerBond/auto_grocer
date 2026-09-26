# ADR 0002: Self-Hosted Remote MCP Endpoint (host `auto-grocer` from this machine)

- **Status:** Proposed
- **Date:** 2026-08-11
- **Deciders:** Repository owner

## Context

Today `auto-grocer` ships as a **local stdio server**. `mcp_server.py` ends in
`mcp.run()`, which FastMCP defaults to the **stdio transport**, and both
`.vscode/mcp.json` and `claude_desktop_config.json` launch it as a child process via
`docker compose ... run --rm -T mcp`. Communication is over the child process's
stdin/stdout on the same machine.

That works for local clients (VS Code, Claude Desktop on this PC) but cannot be reached
by **remote clients** — notably the Claude iOS app and claude.ai, which only support
**remote MCP connectors**: a publicly reachable `https://.../mcp` URL speaking the
Streamable HTTP transport, added through the "Add custom connector" dialog.

The goal of this ADR is a **plan** (not an implementation) to host the existing server
from this desktop so it can be queried remotely, while keeping the current local stdio
path fully working and not weakening the safety posture (this server drives a real HEB
account, cart, and a guarded paid-order tool).

Key facts that shape the design:

- **FastMCP already supports HTTP transports** (`streamable-http`), so no protocol rewrite
  is needed — only a transport switch plus an auth layer.
- The server holds **sensitive state**: a logged-in HEB session (`auth.json` in the
  `auto_grocer_session` volume), the Claude API key, Gmail IMAP creds, and DB creds. A
  public endpoint with no auth would let anyone spend money and read the account.
- `place_order` is **guarded** (disabled unless `AUTO_GROCER_ALLOW_PLACE_ORDER=1`) and
  must **stay disabled** on any internet-exposed instance.
- The desktop is not always on and sits behind a residential NAT; a raw port-forward
  exposes the home IP and the box directly.
- HEB's WAF rate-limits by IP; the remote path must not add uncontrolled traffic to
  heb.com beyond the existing throttler.

## Decision (proposed approach)

Add an **optional remote HTTP transport** to the *same* server, front it with
**authentication**, and expose it over **HTTPS via an outbound tunnel** — never a raw
port-forward. The local stdio path is unchanged and remains the default.

1. **Transport is selected by env var, stdio stays default.** Introduce
   `AUTO_GROCER_TRANSPORT` (`stdio` default | `http`). In `main()`:
   - `stdio` → `mcp.run()` (today's behavior, untouched).
   - `http` → `mcp.run(transport="streamable-http", host=..., port=...)` bound to
     `127.0.0.1` (loopback only) so nothing is exposed except through the tunnel/proxy.
   Host/port come from `AUTO_GROCER_HTTP_HOST` / `AUTO_GROCER_HTTP_PORT`.
2. **Authentication is mandatory in `http` mode.** The server refuses to start in `http`
   mode without a configured auth secret. Two layers, defense-in-depth:
   - A **static bearer token** (`AUTO_GROCER_HTTP_TOKEN`) checked on every request as the
     minimum bar, and/or
   - **OAuth** via the connector dialog's client-id/secret fields if we later want the
     Anthropic-native flow. Start with bearer; treat OAuth as a follow-up.
3. **HTTPS via an outbound tunnel, not a port-forward.** Use a tunnel that dials out from
   the desktop so no inbound firewall/NAT rule and no home-IP exposure is required.
   Candidates (pick one in implementation): **Cloudflare Tunnel** (stable hostname, free,
   access policies), **Tailscale Funnel** (simplest, ties to tailnet), or **ngrok**
   (quickest, paid for a stable domain). The tunnel terminates TLS and forwards to the
   loopback HTTP port from step 1.
4. **Keep `place_order` disabled on the exposed instance.** The remote deployment runs
   with `AUTO_GROCER_ALLOW_PLACE_ORDER` unset. Paid orders remain a local-only,
   deliberate action. `checkout` (review, no charge) stays available remotely.
5. **Run it as a separate, long-lived container** distinct from the on-demand
   `docker compose run` used by local stdio. Add an `mcp-http` compose service (or a
   profile) that runs detached with `restart: unless-stopped`, publishes only to
   `127.0.0.1`, and shares the same `auto_grocer_session` volume and `.env`. The tunnel
   runs as its own sidecar/service pointing at that port.
6. **Session lifecycle is unchanged.** The HTTP instance reuses the same exported
   `auth.json` + persisted hashes and the same refresh skills. Because the box may sleep,
   document that the tunnel + container must be running for the remote endpoint to answer,
   and that a stale session still surfaces the existing `NOT_AUTHENTICATED` /
   `OPERATION_NOT_CAPTURED` recovery path.

## Proposed implementation plan (phased, each phase independently verifiable)

- **Phase 0 — Transport switch (local only).**
  - Add `AUTO_GROCER_TRANSPORT` handling in `mcp_server.main()`; default `stdio`
    unchanged. In `http` mode bind `127.0.0.1:<port>`.
  - Verify: `AUTO_GROCER_TRANSPORT=http` server answers an MCP handshake on localhost
    (e.g., `curl`/an MCP client), and the default run still works stdio.
- **Phase 1 — Auth gate.**
  - Require `AUTO_GROCER_HTTP_TOKEN` in `http` mode; reject unauthenticated/incorrect
    requests with 401. Fail fast at startup if unset.
  - Verify: requests without the token are rejected; with the token succeed. Add a unit
    test for the auth check.
- **Phase 2 — Containerized HTTP service.**
  - Add an `mcp-http` compose service (detached, `127.0.0.1`-only publish,
    `restart: unless-stopped`, shared session volume, `AUTO_GROCER_ALLOW_PLACE_ORDER`
    unset). Reuse the existing image.
  - Verify: `docker compose up -d mcp-http`; localhost handshake works; `place_order`
    reports disabled.
- **Phase 3 — HTTPS tunnel.**
  - Stand up the chosen tunnel (Cloudflare Tunnel recommended for a stable hostname +
    access policy) forwarding `https://<name>/mcp` → loopback port. Optionally enforce a
    second auth layer at the tunnel edge.
  - Verify: the URL is reachable externally over HTTPS and still requires the bearer token.
- **Phase 4 — Connect the iOS/web client.**
  - Add the `https://<name>/mcp` URL via "Add custom connector"; supply the token/OAuth.
  - Verify: a read-only tool (`auth_status`, `get_cart`) succeeds from the phone; confirm
    `place_order` is unavailable.
- **Phase 5 — Docs + ops.**
  - README section: how to start/stop the remote endpoint, rotate the token, and the
    "desktop must be awake" caveat. Note WAF/throttling still applies.

## Security considerations (load-bearing)

- **No unauthenticated exposure, ever.** `http` mode must not start without a token; the
  tunnel must not point at a tokenless server.
- **Loopback binding + outbound tunnel** avoids opening inbound ports or leaking the home
  IP; the desktop is never directly addressable.
- **Least capability remotely:** `place_order` stays disabled; consider a remote
  read-mostly profile if we want to also hide cart-mutating tools.
- **Secret hygiene:** the bearer token lives only in `.env` / the tunnel config (both
  gitignored); rotate on any suspicion. The HEB session, Claude key, and Gmail creds are
  already only in `.env` and the session volume.
- **Rate/abuse:** keep the existing GraphQL throttler; the auth gate prevents third parties
  from driving traffic to heb.com through the endpoint.

## Consequences

**Positive**
- The same server becomes reachable from the Claude iOS app / web with no protocol rewrite.
- Local stdio usage is completely unaffected (opt-in transport).
- Outbound tunnel + loopback binding + mandatory auth is a defensible posture for a
  money-touching endpoint.

**Negative / risks**
- New moving parts to run and monitor (long-lived container + tunnel); the endpoint only
  answers while the desktop is awake and both are up.
- Introduces an internet-reachable surface for a sensitive account — security depends on
  the auth gate and keeping `place_order` disabled.
- A third-party tunnel provider becomes part of the trust chain.

## Alternatives considered

- **Raw router port-forward + DIY TLS** — rejected: exposes the home IP and the box
  directly, requires managing certs/NAT, and is easy to misconfigure into an open endpoint.
- **Rewrite as a cloud-hosted service** — rejected for now: defeats the explicit goal of
  hosting *from this computer* and moves the HEB session off the trusted machine.
- **VPN-only access (e.g., Tailscale without Funnel)** — viable and more private, but the
  Claude iOS app can't be guaranteed to sit on the tailnet when adding a public connector;
  kept as a fallback if public exposure is undesirable.
- **Leave stdio-only** — rejected: it structurally cannot serve remote clients, which is
  the whole objective.
