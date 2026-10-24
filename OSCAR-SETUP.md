# Set up Calendar with Connected accounts

Calendar is a read-only viewer. Google OAuth clients, refresh tokens and consent live
only in **Connected accounts** (`wizard-connectors`), never in Calendar.

1. Install Connected accounts and Calendar on your Wizard.
2. Approve Calendar → Connected accounts in Wizard app permissions. `uses` offers
   compatibility, not permission: a missing/revoked grant makes no provider calls.
3. Open Calendar → **Open Connected accounts**. Add your own Google OAuth app there
   once, following that app's redirect/consent instructions. Never paste credentials,
   OAuth callbacks or verification codes into agent chat or Calendar.
4. Connect your Google account(s), allowing read-only Calendar access. Return to
   Calendar → Settings → **Sync now**. Linked accounts and last successful sync appear
   there. Reauthorization is also handled in Connected accounts.

## Routing and permissions

The App Manager supplies `${APP_DATA_DIR}/wizard/grants.json`. The package mounts its
parent directory read-only at `/wizard` (so atomic replacement and key rotation work)
and sets `WIZARD_GRANTS_FILE=/wizard/grants.json`. The outgoing key may be stored under
`wizard-connectors` or `slot:calendar-source`; every provider call sends `X-Wizard-Grant`.
Calendar never logs or exports that key. `enforce: false` does not authorize calls without
an outgoing grant. Missing/malformed file, key or endpoint yields `not_linked`.

Provider URL precedence: grants `provider_endpoints["wizard-connectors"]`, then
`provider_endpoints["slot:calendar-source"]`, then `CONNECTORS_URL`. No guessed Docker
container hostname is baked in. Do not use the provider's internal service URL as an
owner-facing link. Its status response supplies `setup_url` (default app path
`/wizard-connectors/`). WizardApp currently has no open-app navigation API; the setup
link uses `target=_top`, an EXTEND candidate rather than a shell fork.

## Sync and failure behavior

The in-process worker syncs on startup, every `CALENDAR_SYNC_MINUTES` (default 10),
and after `POST /api/sync {}` (202; poll GET `/api/sync` until `syncing` is false).
It calls status → calendars → events for each calendar over today minus 30 days to
 today plus 180 days. No Google SDK, gog binary, cron job or external import is required.
The backend window uses `CALENDAR_TIMEZONE`, default UTC. If that environment variable
is unset/empty, the UI displays in the browser's timezone; explicitly setting an IANA
zone makes all viewers use it. Snapshot `timezone` remains the server/window zone.

Snapshots use the same `validate()` + atomic `save()` path as manual imports. Existing
calendar colors and hidden preferences survive; new calendars are visible and retain
Google's #RRGGBB color, or use skin palette tokens if absent. IDs are stable hashes of
(account, provider calendar ID), not email addresses embedded in public URLs.
Events dedupe across calendars/accounts by normalized (title, start instant, end instant).
Cancelled events are omitted; all-day end dates are exclusive. Raw validated per-calendar
rows stay private in the snapshot cache to retain last-good data on partial failures.
A failed calendar keeps its previous events and exposes a per-calendar error; truncated
results are failures, not success. Malformed/unsafe provider payloads reject the entire
new snapshot. No incomplete candidate is written. Deletions on successful calendars apply.
`last_success` advances only on a fully successful sync, even if content is unchanged.

GET `/api/sync` and `/api/health` detail expose states `not_linked`, `needs_google_app`,
`needs_account`, `needs_permission`, `ok`, `error`, plus `last_success`, `last_error`,
`accounts`, `calendar_errors`, `setup_url`, `syncing`, and `interval_minutes`.
MCP tools `calendar_events` and `sync_status` are read-only and do not start a sync.

## Manual import and legacy adapter

Settings → Import snapshot JSON and `POST /api/import` remain supported and label their
source `manual_import`. They replace the local snapshot only; the next connected sync
replaces it again. Back up with GET `/api/export` first. Export includes hidden events
and the private last-good cache; protect it like the owner's calendar. No fixture is
automatically imported. `tools/gog_import.py` + `connector.example.json` remain optional
legacy tools for users already operating their own gog installation; they are not the
recommended setup and no scheduler is installed for them.

Import contract (4 MiB): `schemaVersion: 1`, IANA `timezone`, up to 100 unique
`calendars: [{id,name,color?}]`, up to 10,000 unique `events` with `id`, `cal`, `title`,
`start`, `end`, boolean `allDay`. Timed dates require UTC offsets; all-day dates are
YYYY-MM-DD. End must follow start. Optional location (500), description (4000), link
and meet (2000) are accepted; URLs must be credential-free https. Calendar IDs/names
are at most 300 chars, event IDs 650, titles 300. Invalid input returns 400, unsafe
Host/Origin 403, oversize 413, storage failure 500. Repeating content preserves digest
and content timestamp. Visibility: `POST /api/calendars/visibility {id,visible}`.

Runtime: stdlib Python, `DATA_DIR` (container `/data`), `PORT` 8799, `BIND`, exact
`WIZARD_TRUSTED_HOSTS`/`WIZARD_TRUSTED_ORIGINS`, and `WIZARD_CORE_DIR` for standalone
shared WizardApp resources. Preserve the data volume on upgrade. The server is
single-owner, not a public authentication boundary: expose only via Wizard's gateway.
Revoke Google through Connected accounts and revoke the app grant to stop access.
