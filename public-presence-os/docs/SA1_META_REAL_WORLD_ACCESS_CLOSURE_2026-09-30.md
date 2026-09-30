# S-A1 — META REAL-WORLD ACCESS CLOSURE

Date: 2026-09-30  
Scope: PUBLIC PRESENCE OS — TEXT/PHOTO  
Authority posture: READ-ONLY / SHADOW. No social writes authorized.

## Result

**S-A1 REAL-WORLD ACCESS: PASS (identity and read-only API binding).**

The production-facing Meta identities were verified interactively against the official Meta developer tools without storing or committing access tokens, app secrets, passwords, 2FA codes, or other credentials.

### Facebook Page

- Public identity: `Mihai Cismaru`
- Page ID: `2816314015107071`
- Graph probe: `GET /me/accounts?fields=id,name,tasks,instagram_business_account`
- Result: Page returned successfully through the `presence os` Meta app.
- Read-only permissions enabled for testing:
  - `public_profile`
  - `pages_show_list`
  - `pages_read_engagement`
- Write permissions remain disabled.

### Instagram Professional

- Name: `Mihai Cismaru`
- Username: `m.cismaru`
- Instagram Professional ID: `17841429701593250`
- Facebook Page binding returned by Graph as `instagram_business_account`.
- Identity probe: `GET /17841429701593250?fields=id,username,name`
- Result: ID / username / name matched the intended production identity.
- Route selected: Instagram API with Facebook Login.
- Write permissions remain disabled.

### Threads

- Name: `Mihai Cismaru`
- Username: `m.cismaru`
- Threads user ID: `28391623420464631`
- `threads_basic`: Ready for testing.
- Identity probe host: `graph.threads.net`
- Identity probe: `GET /me?fields=id,username,name`
- Result: ID / username / name matched the intended production identity.
- `threads_content_publish`, delete, keyword-search, insights, mentions and other non-basic permissions remain disabled unless separately justified by a later capability gate.

## Meta app

- App name: `presence os`
- App ID: `1488219383133581`
- App state at closure: unpublished / development.
- Use cases configured:
  1. Manage everything on your Page
  2. Manage messaging & content on Instagram
  3. Access the Threads API
- Business portfolio selected during creation: `Mihail Andrei Cismaru`.
- Business verification was not required to complete these owner/test identity probes.

## Security evidence

- No token value was copied into repository or documentation.
- No app secret was revealed or stored.
- No credential was supplied to ChatGPT.
- No write permission was required for the identity probes.
- No post, comment, reply, reaction, follow/unfollow, delete or other social write was executed.

## Canonical authority

Global safety posture remains unchanged:

- `LIVE_WRITE = OFF`
- kill switch remains engaged
- CP58 authority boundary remains in force
- Facebook Page + Instagram Professional + Threads are the active Meta lanes
- LinkedIn remains production-API-gated
- X remains excluded while useful API access is paid
- Bluesky remains HOLD_ROI

## S-A2 entry gate

S-A2 LIVE OBSERVABILITY may begin only with credential references supplied through runtime environment / secret storage. Tokens and secrets must never be committed.

First S-A2 unit:
1. define read-only credential/env contract;
2. implement normalized Meta read adapters for the three verified identities;
3. persist cursors/event IDs for incremental sync;
4. prove replay/dedup without external writes;
5. keep unavailable metrics as `UNKNOWN`.

This checkpoint closes identity/access discovery only. It does **not** authorize publishing, comments, replies, reactions, messaging, follow/unfollow or deployment.
