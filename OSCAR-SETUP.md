# Calendar setup

Calendar 0.3.0 reads calendars from two sources that work together: **Connected accounts**
(Google OAuth, grant-scoped sync) and **private Google iCal links**. Snapshot import and the
legacy gog adapter remain as advanced options.

## Boundaries

Calendar is a read-only calendar viewer. It can sync through Connected accounts, subscribe to
a private Google iCal feed and import a validated snapshot, but it cannot create, edit, delete or RSVP
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

## B. Sync through Connected accounts

Calendar is a read-only viewer. Google OAuth clients, refresh tokens and consent live
only in **Connected accounts** (`connected-accounts`, formerly `wizard-connectors`), never in Calendar.

1. Install Connected accounts and Calendar on your Wizard.
2. Calendar declares `uses: [connected-accounts]`. Current WAM creates the declared
   connection automatically once both apps are installed. Approve it in App Manager →
   Connections only if pending (sensitive provider) or explicitly reconnect it after a
   denial. Older proposal-based installs may ask for approval. A missing/revoked grant
   makes no provider calls. See RELEASE.md for source evidence.
3. Open Calendar → **Open Connected accounts**. Add your own Google OAuth app there
   once, following that app's redirect/consent instructions. Never paste credentials,
   OAuth callbacks or verification codes into agent chat or Calendar.
4. Connect your Google account(s), allowing read-only Calendar access. Return to
   Calendar → Settings → **Sync now**. Linked accounts and last successful sync appear
   there. Reauthorization is also handled in Connected accounts.

### Routing and permissions

The App Manager supplies `${APP_DATA_DIR}/wizard/grants.json` and injects its
parent directory read-only at `/wizard` (so atomic replacement and key rotation work)
and sets `WIZARD_GRANTS_FILE=/wizard/grants.json`. The app recipe declares no grants
mount. The canonical caller is `wizard-calendar`, not the legacy launcher id
`calendar`. The outgoing key may be stored under
`connected-accounts` (new installs), `wizard-connectors` or `slot:calendar-source`
(compatibility); every provider call sends `X-Wizard-Grant`.
Calendar never logs or exports that key. `enforce: false` does not authorize calls without
an outgoing grant. Missing/malformed file, key or endpoint yields `not_linked`.

Provider URL precedence: grants `provider_endpoints["connected-accounts"]`, then
`provider_endpoints["wizard-connectors"]`, then
`provider_endpoints["slot:calendar-source"]`, then `CONNECTORS_URL`. No guessed Docker
container hostname is baked in. Do not use the provider's internal service URL as an
owner-facing link. Its status response supplies `setup_url` (default app path
`/wizard-connectors/`). WizardApp currently has no open-app navigation API; the setup
link uses `target=_top`, an EXTEND candidate rather than a shell fork.

### Sync and failure behavior

The in-process worker syncs on startup, every `CALENDAR_SYNC_MINUTES` (default 10),
and after `POST /api/sync {}` (202; poll GET `/api/sync` until `syncing` is false).
It calls status → calendars → events for each calendar over today minus 60 days to
today plus 400 days, split into two bounded requests. No Google SDK, gog binary, cron job or external import is required.
The backend window uses `CALENDAR_TIMEZONE`, default UTC. If that environment variable
is unset/empty, the UI displays in the browser's timezone; explicitly setting an IANA
zone makes all viewers use it. Snapshot `timezone` remains the server/window zone.

Snapshots use the same `validate()` + atomic `save()` path as manual imports. Existing
calendar colors and hidden preferences survive; new calendars are visible and retain
Google's #RRGGBB color, or use skin palette tokens if absent. IDs are stable hashes of
(account, provider calendar ID), not email addresses embedded in public URLs.
Events dedupe across calendars/accounts by normalized (title, start instant) or
(iCalUID, start instant).
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

### Coexistence with iCal subscriptions

Connected accounts calendars and iCal subscriptions are stored side by side. A Connected
accounts sync keeps the saved iCal calendars and events untouched; an iCal refresh or source
change keeps the Connected accounts calendars, per-calendar cache, errors and last-success
marker. `POST /api/sync {}` refreshes the iCal links before replying and queues a Connected
accounts refresh (202; poll GET `/api/sync`); with only iCal links it returns 200 when done.

## C. Add a private Google iCal link

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
10,000 visible events, and use bounded RRULE length, token-cardinality and recurrence-expansion
budgets. Unsupported or malformed calendar data fails closed without stopping later saved
calendars from refreshing.

Saved sources refresh every 15 minutes by default. **Sync now** refreshes immediately.
A failed refresh retains the last-good events and shows a source-level error without exposing
the private URL. Removing a source deletes that source's saved URL and imported events from
Calendar; it does not change the provider calendar.

`webcal://` is only an input convenience. Calendar always fetches over HTTPS.

## D. Optional legacy hidden/color preference import (owner-run only)

This is **not automatic**, does not read the legacy app's files itself, and has not
been run on the live calendar. First connect and sync the packaged Calendar, then
back up `GET /api/export`. `POST /api/preferences/import` accepts the old config's
`calendars: [{id,color?}]` and `hidden: [id]`. Other fields (names, accounts, tokens,
events) are ignored and never saved. Colours must be `#RRGGBB`.

Exact local ids take precedence; otherwise legacy Google ids match `provider_id`.
When the same Google calendar is visible through several accounts, the preference
applies to every matching copy. No name/email guessing is performed. Preferences
for calendars not mentioned in the import are preserved. Matched calendars absent
from `hidden` become visible. Response `matched` counts local calendars; `unmatched`
lists old ids that are not currently available. Connect missing calendars and
repeat the import if desired. Invalid input is rejected atomically (HTTP 400), and
unmatched ids are not saved as pending future preferences. Events, source metadata,
last successful sync and content timestamp are not replaced. Later syncs preserve
imported colour/visibility for calendars that remain present.

On the owner machine, with `CALENDAR_URL` set to the packaged app's private loopback
URL (or an already authenticated owner route), run deliberately:

```sh
# Export contains private events; keep this backup owner-only.
umask 077
curl --fail --silent --show-error "$CALENDAR_URL/api/export" > calendar-before-prefs.json
# Send ONLY preferences; never copy credentials or add a legacy home-directory mount.
python3 -c 'import json,pathlib; d=json.loads((pathlib.Path.home()/".hermes/data/apps/wizard-calendar/config.json").read_text()); print(json.dumps({"calendars":[{k:c[k] for k in ("id","color") if k in c} for c in d["calendars"]],"hidden":d.get("hidden",[])}))' > calendar-prefs.json
curl --fail --silent --show-error -H 'Content-Type: application/json' \
  --data-binary @calendar-prefs.json "$CALENDAR_URL/api/preferences/import"
curl --fail --silent --show-error "$CALENDAR_URL/api/export" > calendar-after-prefs.json
```

Check `matched`/`unmatched` and the exported hidden ids/colours before deleting the
private payload. To undo immediately, POST the saved export to `/api/import` (this
also restores its events). For a later rollback, restore only preference values
from the backup so newer events are not overwritten.

## E. Manual import and legacy adapter

Settings → Import snapshot JSON and `POST /api/import` remain supported and label their
source `manual_import`. They replace the local snapshot only; the next connected sync
replaces it again. Back up with GET `/api/export` first. Export includes hidden events
and the private last-good cache; protect it like the owner's calendar. No fixture is
automatically imported. `tools/gog_import.py` + `connector.example.json` remain optional
legacy tools for users already operating their own gog installation; they are not the
recommended setup and no scheduler is installed for them.

### Optional operator-managed snapshot connector (gog)

Connected accounts and direct iCal are the normal owner paths. An operator can still generate a read-only snapshot
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

## F. API contracts

### iCal sources

`POST /api/sources`, Content-Type `application/json`, body at most 4 MiB:

```json
{"name":"Personal","url":"https://calendar.google.com/calendar/ical/REDACTED/basic.ics"}
```

The success response contains the source ID, display name, provider and refresh status, but
never the URL. `GET /api/sources` returns the same redacted projection. `POST /api/sync` with
`{}` refreshes all iCal sources and queues a Connected accounts refresh when linked (see Coexistence). `POST /api/sources/remove` accepts the opaque `id` returned by
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
- `CALENDAR_SYNC_MINUTES` Connected accounts sync interval (default 10).
- `WIZARD_GRANTS_FILE` and `CONNECTORS_URL` for Connected accounts routing (see B).
- `ICAL_SYNC_INTERVAL` in seconds (900; set 0 only for isolated tests).
- `WIZARD_TRUSTED_HOSTS` and `WIZARD_TRUSTED_ORIGINS` exact allowlists.
- `WIZARD_CORE_DIR` for the approved standalone shared resource.

No OAuth credential belongs in an app environment variable; the server is single-owner, not a public
authentication boundary: expose only via Wizard's gateway. Revoke Google through Connected accounts and
revoke the app grant to stop access. Preserve and privately back up
the app-data volume when subscriptions must survive a host migration; the JSON export alone
deliberately cannot reconstruct private source links.

## Troubleshooting and rollback

- Connected accounts shows `not_linked`: approve the connection in App Manager → Connections, then Settings → Sync now.
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

Deferred: provider write operations, RSVP, CalDAV, arbitrary ICS hosts,
custom VTIMEZONE definitions and unbounded recurrence rules.
