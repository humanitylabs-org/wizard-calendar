# Calendar setup

## Boundaries

Calendar 0.1.0 is a read-only calendar viewer. It can subscribe to a private Google
iCal feed and can import a validated snapshot, but it cannot create, edit, delete or RSVP
to provider events. Fresh installs are empty.

A Google **Secret address in iCal format** is a bearer secret. Anyone who has it can read
that calendar. Never paste a real link into agent chat, logs, screenshots, issue reports,
Git, test fixtures or command history. Enter it only in Calendar's owner-facing Settings
screen. If it leaks, reset the private address in Google Calendar.

## A. Prove the empty app first

Follow README.md and verify `GET /api/events` has `events: []`, `calendars: []` and
`connected: []`. Test the included synthetic fixture through the UI or API, then restore
`fixtures/empty.json` on the disposable test installation. This proves the viewer and
snapshot path without involving a real account.

## B. Add a private Google iCal link

1. On the owner's device, open Google Calendar.
2. Open **Settings and sharing** for the calendar, then **Integrate calendar**.
3. Copy **Secret address in iCal format**.
4. In Calendar, open **Settings → Add calendar**.
5. Enter a display name, paste the link, and choose **Add calendar**.

The app accepts `https://` and `webcal://` links only when they normalize to the canonical
`calendar.google.com/calendar/ical/.../basic.ics` form. Plain HTTP, other hosts, lookalike
hostnames, alternate ports, embedded credentials and redirects are rejected. The initial
feed is fetched and parsed before the source is saved.

Calendar stores the normalized private URL only in `/data/state.json`, atomically replaced
with mode 0600 inside a mode 0700 data directory. Source authority and its derived snapshot
share that one file, so a crash cannot mix generations or restore a removed source.
The URL is never included in `GET /api/sources`, `GET /api/events`, MCP output, generated
event IDs or owner-facing errors. Fetches ignore inherited HTTP proxy variables, are limited
to 8 MiB, 20,000 raw VEVENT records, 100,000 aggregate recurrence-date values and
10,000 visible events, and use a shared bounded recurrence-expansion budget. Unsupported or
malformed calendar data fails closed without stopping later saved calendars from refreshing.

Saved sources refresh every 15 minutes by default. **Sync now** refreshes immediately.
A failed refresh retains the last-good events and shows a source-level error without exposing
the private URL. Removing a source deletes that source's saved URL and imported events from
Calendar; it does not change the provider calendar.

`webcal://` is only an input convenience. Calendar always fetches over HTTPS.

## C. Optional operator-managed snapshot connector

Direct iCal is the normal owner path. An operator can still generate a read-only snapshot
with gogcli when a private iCal feed is unsuitable. This is separate from Calendar and must
use the recipient's own explicitly authorized account and keyring.

Use gogcli **v0.31.1 or a version with the same flags/output**. Follow the official
https://gogcli.sh instructions. Store secrets in the local password manager or OS keyring;
do not put credentials or verification codes in agent chat, app config, logs or Git.

```sh
export GOG_HOME="$HOME/.config/calendar-connector-gog"
mkdir -p "$GOG_HOME"
chmod 700 "$GOG_HOME"
gog --home "$GOG_HOME" auth credentials set /path/to/your/oauth-client.json
gog --home "$GOG_HOME" --readonly auth add you@example.com --services calendar
gog --home "$GOG_HOME" --no-input --readonly -a you@example.com calendar calendars --all --json
```

Copy `connector.example.json` to a private, untracked path and set mode 0600:

```json
{
  "account": "you@example.com",
  "timezone": "Europe/Lisbon",
  "calendars": [{"id": "primary", "name": "My calendar"}],
  "pastDays": 60,
  "futureDays": 400
}
```

Generate and inspect a snapshot privately, then import it:

```sh
python3 tools/gog_import.py --config /private/path/calendar-connector.json --gog /absolute/path/to/gog --output /private/path/first-snapshot.json
curl --fail -H 'Content-Type: application/json' --data-binary @/private/path/first-snapshot.json http://127.0.0.1:18787/api/import
curl --fail http://127.0.0.1:18787/api/export
```

The adapter uses `--no-input --readonly`, complete pagination and an explicit time window.
Any provider error, timeout, unexpected envelope, incomplete pagination, invalid timestamp
or link aborts the import; the previous snapshot remains. A successful import performs API
readback and compares `contentSha256`. Scheduling this external connector is an operator task;
Calendar does not install a gog scheduler.

## D. API contracts

### iCal sources

`POST /api/sources`, Content-Type `application/json`, body at most 4 MiB:

```json
{"name":"Personal","url":"https://calendar.google.com/calendar/ical/REDACTED/basic.ics"}
```

The success response contains the source ID, display name, provider and refresh status, but
never the URL. `GET /api/sources` returns the same redacted projection. `POST /api/sync` with
`{}` refreshes all sources. `POST /api/sources/remove` accepts the opaque `id` returned by
`POST /api/sources` or `GET /api/sources`; callers must not construct or guess it.
Inspect the readback rather than treating HTTP status alone as proof.

### Snapshot import

`POST /api/import`, Content-Type `application/json`, body at most 4 MiB:

- `schemaVersion`: integer 1; `timezone`: valid IANA string (UTC default).
- `calendars`: up to 100 `{id, name}` objects; unique nonempty strings up to 300 chars.
- `events`: up to 10,000 objects, each with `id` (unique, max 650), `cal` (existing
  calendar ID), `title` (nonempty max 300), `start`, `end`, and boolean `allDay`.
- Timed start/end: ISO timestamps with offsets, for example `2026-10-15T10:00:00Z`.
- All-day start/end: `YYYY-MM-DD`; end is exclusive. End must follow start.
- Optional `location` (500), `description` (4000), `link` and `meet` (2000 each).
  Links must be HTTPS URLs without credentials. Text is rendered escaped, not as HTML.
- Extra fields are discarded. Provider raw JSON and arbitrary metadata are not retained.

Import replaces the visible snapshot atomically while preserving visibility preferences for
retained IDs. It does not delete saved iCal sources. A later source sync re-adds subscribed
events. Repeating identical content yields `changed: false`, the same `contentSha256`, no
duplicates and no new import timestamp. `GET /api/export` includes hidden events but never
saved source URLs. `GET /api/events` respects visibility. MCP `calendar_events` returns the
same visible read-only projection.

Invalid input returns 400; untrusted Host/Origin 403; oversize request 413; storage failure
500. Source fetch failures return a secret-free 400 on initial add and retain the prior state.

## Runtime and data

Data directory: `DATA_DIR` (default `./data`, container `/data`). `state.json` atomically
contains the normalized snapshot, visibility preferences, private iCal URLs and refresh
status. It is mode 0600 in a mode 0700 directory. A pre-subscription `snapshot.json` from
Calendar 0.1.0 is read as the migration baseline and folded into `state.json` on the first
subsequent write; it never contains a private iCal URL.

Runtime environment:

- `PORT` (8799) and `BIND` (127.0.0.1 outside Compose).
- `CALENDAR_TIMEZONE` (UTC).
- `ICAL_SYNC_INTERVAL` in seconds (900; set 0 only for isolated tests).
- `WIZARD_TRUSTED_HOSTS` and `WIZARD_TRUSTED_ORIGINS` exact allowlists.
- `WIZARD_CORE_DIR` for the approved standalone shared resource.

No OAuth credential belongs in an app environment variable. Preserve and privately back up
the app-data volume when subscriptions must survive a host migration; the JSON export alone
deliberately cannot reconstruct private source links.

## Troubleshooting and rollback

- Empty UI: check the source status, date range, Settings visibility and selected day.
- Add fails: confirm the URL is Google's **Secret address in iCal format**, not the public
  calendar page, an embed URL or a copied browser address.
- Source error: choose **Sync now**. Last-good events stay visible while refresh is failing.
- Shared core error: rerun the digest-checked fetch step or fix Wizard's shared-core route.
- 403: configure exact public Host and Origin through the authenticated gateway; never add
  wildcards or trust arbitrary `X-Forwarded-Host` values.
- Leaked URL: reset the private address in Google, remove the old source, and add the new one.
- Rollback: preserve `/data`; restore a backed-up snapshot if necessary. Removing the app-data
  volume permanently deletes the saved source links.

Deferred: provider write operations, RSVP, CalDAV, arbitrary ICS hosts, OAuth account setup,
custom VTIMEZONE definitions and unbounded recurrence rules.
