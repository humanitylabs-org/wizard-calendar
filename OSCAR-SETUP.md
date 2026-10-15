# Oscar setup: wire the recipient's own calendar

## Boundaries

Calendar 0.1.0 is a read-only snapshot viewer, **not an OAuth connection manager**.
Nothing is connected on install. The app container has no gog binary, OAuth tokens,
keyring mount, account IDs or scheduled tasks. Obtain the recipient's explicit permission
before authorizing an account or replacing an imported snapshot. Never copy anyone else's
calendar config, data directory, keyring or OAuth client. This release did not perform live
provider authorization; the adapter was checked with synthetic gog-shaped results only.

## A. Install and prove empty first

Follow README.md and verify `GET /api/events` has `events: []`, `calendars: []`,
`connected: []`. Test the included fixture through UI or curl and then explicitly restore
`fixtures/empty.json` on the disposable test installation. This proves UI/API and import
without involving a real account.

## B. Configure Google's read-only export on the recipient's machine

Use gogcli **v0.31.1 or a version with the same flags/output**. Installation and provider OAuth
client registration are operator prerequisites; use the official https://gogcli.sh instructions.
The commands below were checked against v0.31.1 help, not a live recipient account.
Create an isolated gog home and use the recipient's approved OAuth client. Store secrets via
the local password manager/OS keyring; do not paste credentials or verification codes into chat.
The owner completes Google consent interactively on their own device.

```sh
# Paths and account below are operator-owned inputs, not bundled values.
export GOG_HOME="$HOME/.config/calendar-connector-gog"
mkdir -p "$GOG_HOME"
chmod 700 "$GOG_HOME"
gog --home "$GOG_HOME" auth credentials set /path/to/your/oauth-client.json
# Substitute the owner's approved account, and review the read-only consent scope.
gog --home "$GOG_HOME" --readonly auth add you@example.com --services calendar
# Read-only list; choose calendars explicitly, rather than importing all subscriptions.
gog --home "$GOG_HOME" --no-input --readonly -a you@example.com calendar calendars --all --json
```

On a headless host use gog's documented `--remote --step 1` and `--remote --step 2`
flow through a secure local credential UI, not agent chat. No consent URLs, callback codes
or keyring passwords should enter app config, logs, Git, container images or this release.
For unattended operation arrange keyring unlocking in the connector service's secure
credential environment; do not place passwords in the command line. No scheduler is
installed or enabled by Calendar.

Copy `connector.example.json` to a **private, untracked** path. Set mode 0600.
Exact keys:

```json
{
  "account": "you@example.com",
  "timezone": "Europe/Lisbon",
  "calendars": [{"id": "primary", "name": "My calendar"}],
  "pastDays": 60,
  "futureDays": 400
}
```

Replace account with the explicitly authorized address. Calendar IDs come from `calendar
calendars`; `primary` is a valid selected calendar alias. Timezone must be an IANA name.
Each selected calendar becomes a separate visible calendar. Overlapping events on different
calendars remain separate intentionally; deduplication is by event ID within one calendar.
Attendee names/emails are not imported. Title, time, location, description and provider links
are included and may themselves be private. Omit undesired calendars from the config.

```sh
# Uses GOG_HOME from the environment; never consults a hardcoded keyring file.
python3 tools/gog_import.py --config /private/path/calendar-connector.json --gog /absolute/path/to/gog --output /private/path/first-snapshot.json
# Inspect the snapshot privately. Then import through Settings, or explicitly:
curl --fail -H 'Content-Type: application/json' --data-binary @/private/path/first-snapshot.json http://127.0.0.1:18787/api/import
curl --fail http://127.0.0.1:18787/api/export
# For repeated local refreshes, after approval:
python3 tools/gog_import.py --config /private/path/calendar-connector.json --gog /absolute/path/to/gog --url http://127.0.0.1:18787
```

`--output` refuses an existing file and creates a new one mode 0600. The adapter uses
`--no-input --readonly`, `--all-pages`, `--max 250`, and an explicit time window per calendar.
Any provider error, timeout, unexpected envelope, incomplete pagination, invalid timestamp
or link aborts the whole import; the previous app snapshot is retained. No partial sync is
committed. A successful import performs API readback and compares contentSha256.

If wanted, the recipient's agent can arrange an OS scheduler for the last command every ten
minutes with single-job locking, protected environment, explicit working directory, private
logs and failure alerts. **This is future operator setup, not installed by this test release.**
The app's Reload button rereads the stored snapshot only; it does not contact Google.
For remote gateways, use `--output` plus the gateway's authenticated import route; the
bundled direct adapter deliberately refuses non-loopback upload URLs.

## C. Exact import/API contract

`POST /api/import`, Content-Type application/json, body at most 4 MiB:

- `schemaVersion`: integer 1; `timezone`: valid IANA string (UTC default).
- `calendars`: up to 100 `{id, name}` objects; unique nonempty strings up to 300 chars.
- `events`: up to 10,000 objects, each with `id` (unique, max 650), `cal` (existing
  calendar ID), `title` (nonempty max 300), `start`, `end`, and boolean `allDay`.
- Timed start/end: ISO timestamps **with offsets** (e.g. `2026-10-15T10:00:00Z`).
- All-day start/end: `YYYY-MM-DD`; end is **exclusive**. End must follow start.
- Optional `location` (500), `description` (4000), `link` and `meet` (2000 each).
  Links must be https URLs without credentials. Text is rendered escaped, not as HTML.
- Extra fields are discarded. Do not rely on preserving provider raw JSON or arbitrary metadata.

Import replaces the full snapshot atomically, preserving hidden-calendar preferences for
retained IDs. Repeating identical content yields `changed: false`, same `contentSha256`,
no duplicate events and no new import timestamp. `GET /api/export` includes hidden events;
`GET /api/events` respects visibility. `POST /api/calendars/visibility` accepts
`{"id":"primary","visible":false}`. Invalid input returns 400; untrusted Host/Origin 403;
oversize request 413; storage failure 500. Inspect API readback, not HTTP status alone.
MCP `calendar_events` returns the same visible read-only snapshot.

Data directory: `DATA_DIR` (default `./data`, container `/data`), `snapshot.json` only.
Runtime env: `PORT` (8799), `BIND` (127.0.0.1 outside Compose), `CALENDAR_TIMEZONE` (UTC),
`WIZARD_TRUSTED_HOSTS` (comma-separated exact host:port), `WIZARD_TRUSTED_ORIGINS`
(exact scheme://host:port), `WIZARD_CORE_DIR` (standalone approved shared resource directory).
No OAuth credentials belong in any of these app variables.

## Troubleshooting / rollback

- Empty UI: check exported snapshot, timezone/date range, Settings visibility and selected day.
- Shared core error: rerun the digest-checked fetch step or fix Wizard's shared-core gateway route.
- 403: configure exact public Host and Origin through the authenticated gateway; do not trust
  `X-Forwarded-Host` from arbitrary clients or add wildcards.
- gog failure: reauthorize the intended account locally; validate `GOG_HOME`, keyring access,
  OAuth scope and calendar ID without exposing provider stderr publicly.
- Revoke access through the owner's Google account when removing the external connector.
  Stop its scheduler separately. The Calendar service has no provider token to revoke.
- Restore a backed-up snapshot through the import endpoint; keep data volume across app rollback.

Deferred: self-service OAuth, credential UX, periodic sync management, token refresh recovery,
connection health/permission diagnostics, ICS/CalDAV adapters and provider write operations.
