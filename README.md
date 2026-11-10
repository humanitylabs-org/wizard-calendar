# Calendar 0.3.0

Day, Week and Month views of read-only calendars, from two sources that work together:
**Connected accounts** (bring your own Google OAuth app once, then authorize accounts and
read-only Calendar access there) and **private Google iCal links** added in Settings.
Calendar never stores Google credentials and never creates or edits provider events. See
[OSCAR-SETUP.md](OSCAR-SETUP.md). **Fresh installs are empty** and offer both setups; no
accounts, events, contacts, tokens or live connector config ship in this app. The sample
under `fixtures/` is synthetic and is never imported automatically. A private iCal link is a
bearer secret: keep the data volume and backups private, and never paste the link into chat
or logs. Advanced snapshot import remains available.

The worker refreshes on startup, every ten minutes (`CALENDAR_SYNC_MINUTES`), and from
**Settings → Sync now**. It uses the owner's app-to-app grant, not an external gog cron.
Provider endpoints come from the grants file first, with `CONNECTORS_URL` as an explicit
fallback; missing grants/keys/endpoints yield `not_linked`. No container hostname is guessed.
The last-good snapshot remains available during outages; per-calendar failures retain
those calendars' events and surface errors. Invalid payloads never replace saved data.
Visibility and stored calendar color preferences survive sync. The UI uses the live
Wizard skin's calendar palette, including its holiday role. Events dedupe across accounts
by (title, start) or (iCalUID, start), normalizing title case/whitespace and timed UTC instants.

The optional **Owner timezone** install-form field sets `CALENDAR_TIMEZONE` (an IANA
zone). If blank, the sync window (today −60 to +400 days, split into two bounded provider requests) uses UTC and the UI
displays the browser timezone; an explicit owner zone takes precedence in the UI.
Manual snapshot import remains available for fixtures/backups and is labelled separately;
the next successful connected sync replaces manual data.

Live parity details, QA and the coordinated provider prerequisite for notes/Meet/guest
counts are in [PARITY.md](PARITY.md). A lexical parity PASS alone does not authorize cutover.

## Image install

The Store recipe pulls the public multi-arch (amd64 + arm64) image
`ghcr.io/humanitylabs-org/wizard-calendar`, pinned by tag and digest in
`runtipi/docker-compose.yml`. It is built from this repo by
`.github/workflows/app-image.yml`. No source checkout is mounted at `/app`.
See [RELEASE.md](RELEASE.md) for the package contract and release checks.

For a disposable standalone test after pulling the image, run:

```sh
python3 tools/run_portable.py start
curl --fail http://127.0.0.1:18787/wizard-calendar/healthz
```

Open **http://127.0.0.1:18787/wizard-calendar/**. It starts empty with “Connect your
Google calendar.” This helper fetches the pinned shared WizardApp client into an
isolated core volume; it does not build or pull the app image. Set `DOCKER_CMD` for
another Docker context. Use `--project calendar-personal --port 18788` for an
independent instance; reuse the project name to retain its data.

The server accepts `/wizard-calendar/` and the unprefixed routes. Wizard's gateway
path stays `/wizard-calendar/`; manifest `view.path: /` is the upstream service root.
The main service is **1000:1000**, read-only, all capabilities dropped, with a small
`/tmp` tmpfs and no-new-privileges. An offline, one-shot init service has only CHOWN
to prepare the fresh root-owned `/data` bind for that user. It does not traverse or
rewrite snapshot files. The managed app stores all state in `${APP_DATA_DIR}/data`.

The helper publishes loopback only and sets exact Host/Origin allowlists. These are
not caller authentication: never expose this single-owner service directly to a
LAN or the Internet. Remote access belongs behind Wizard's authenticated gateway.
Without an explicit origin override, requests must have a validated Host and a
same-host HTTP/HTTPS Origin. WAM supplies the fresh box's trusted hosts/origins.

## Add a Google calendar

1. In Google Calendar, open **Settings and sharing → Integrate calendar** for the calendar.
2. Copy **Secret address in iCal format**. Do not use a public link for a private calendar.
3. In Calendar, open **Settings → Add calendar**, enter a name, paste the link, and choose
   **Add calendar**. `https://` and `webcal://` Google Calendar links are accepted.

Calendar tests the feed before saving it. The owner-facing API and screen never return the
private URL. Each saved feed refreshes every 15 minutes by default and can be refreshed with
**Sync now**. A failed refresh keeps the last good events and shows a source-level error.
Removing a source deletes its imported events and saved link from Calendar; it does not change
or delete the Google calendar. Revoke a leaked link by resetting the private URL in Google.

## Fixture/import proof

```sh
curl --fail -H 'Content-Type: application/json' --data-binary @fixtures/example.json http://127.0.0.1:18787/api/import
curl --fail http://127.0.0.1:18787/api/export
# Repeat the first command: changed must be false, with two events (no duplication).
```

Or choose **Settings → Import snapshot JSON**, select `fixtures/example.json`, and approve
replacement. Navigate to 15 October 2026; the timed planning session and all-day example
must appear. Tap either for details; Back closes details and leaves the app open. Switch
Day/Week/Month, hide/show the fixture calendar in Settings, then export the snapshot.

Restore an empty **test** instance by importing `fixtures/empty.json` using the same command
or file picker. This replaces the visible snapshot, not provider events or saved iCal sources;
a later sync will restore subscribed events. Never clear actual user data without permission.
The source fixture is not loaded by the server on startup.

## Update, backup, remove

```sh
curl --fail http://127.0.0.1:18787/api/export -o calendar-backup.json
# After loading the newer approved image and updating the recipe:
python3 tools/run_portable.py start
curl --fail http://127.0.0.1:18787/api/export
# Stop/remove service but keep imported data:
python3 tools/run_portable.py stop
# Reinstall; the previous snapshot remains:
python3 tools/run_portable.py start
```

The helper never deletes its named data volume (`calendar-test_data` by default). Do not
manually delete it on update. Backups and the data volume contain private calendar information;
store them privately. `GET /api/export` backs up events and visibility, but deliberately excludes
private iCal links. Back up the protected app-data volume to preserve subscriptions across a
host migration. Importing a backup restores events; visibility preferences persist in the data volume.
The service never seeds, resets or migrates another installation. On startup it calls only the
granted Connected accounts provider, never Google directly, and a fresh install makes no Google
requests. Saved iCal sources refresh periodically (`ICAL_SYNC_INTERVAL`, default 900 s).

## Wizard package / developer option

`wizard.md`, `runtipi/config.json`, `runtipi/docker-compose.yml`, `openapi.json`
and `skill/SKILL.md` form the Wizard package. `runtime.package: image` uses the
published public multi-arch image; the Dockerfile is `app/Dockerfile` (Python slim plus tzdata).
`python3 tools/package_runtime.py --check` verifies generated recipe agreement.
Root `compose.yml` is a separate developer-only build option, not the Store recipe.
Wizard serves its shared client and hosts the iframe via shared app services.
Catalog publication and activation remain separate release-owner steps.

API: `GET /healthz`, `GET /api/health`, `GET /api/events`, `GET /api/export`,
`POST /api/import`, `POST /api/calendars/visibility`, `GET /api/sync`, `POST /api/sync {}`
(refreshes iCal links and queues a Connected accounts refresh), redacted `GET /api/sources`,
`POST /api/sources` and `POST /api/sources/remove`.
MCP: `POST /mcp`, read-only tools `calendar_events` and `sync_status`.
The same routes work beneath `/wizard-calendar/`. See OSCAR-SETUP.md for input limits and
source restrictions.
WAM injects `${APP_DATA_DIR}/wizard:/wizard:ro` and
`WIZARD_GRANTS_FILE=/wizard/grants.json`; no hand-written bridge is required.
`uses: [connected-accounts]` declares the exact provider app id. Its endpoint takes
precedence over `CONNECTORS_URL`. Old `wizard-connectors` and `slot:calendar-source`
grants remain readable, but are not extra default grants. See RELEASE.md for
fresh-install grant creation, owner consent, and sensitive/disconnected cases.

The read-only live-copy comparison found Day/Week/Month, Today, gear, palette and shared
Back/theme already present in the package. They are retained, not replaced by legacy
OAuth callback forms, hardcoded owner zones, root history guards or local skin storage.
WizardApp.nav lacks openApp; setup uses provider `setup_url` with `target=_top` as an
EXTEND candidate. No wizard-ux/shell changes are included.

## Try changes (feature switches)

New Calendar features land switched off. Each one is a switch in **Settings > Try changes**, kept on
the box per owner in `DATA_DIR/switches.json` and served at `GET/POST /wizard-calendar/api/switches`
(`wizard.app-switches/1`, see wizardos-tracker `docs/app-switches.md`), so the Tracker card can flip it.
POST needs the box's own `Origin`, `X-Wizard-Switch: 1` and a JSON body `{"id": "...", "on": true}`.

| Switch | Name | What it does |
|---|---|---|
| `compact-header` | Compact top bar | One slim header row (date, navigation, status, view switcher on wide windows, Today, Settings) so Day and Week show about 1.3 to 2.3 more hours without scrolling. |
| `trackpad-swipe` | Trackpad day swipe | In Day and Week, a two-finger sideways swipe on a trackpad (or Shift + mouse wheel) moves the grid with the fingers and settles on the nearest day, like Mac Calendar. Swipe left goes forward, right goes back; a longer or faster swipe moves several days. Week becomes a sliding 7-day window (Today and switching view return it to Monday first). Vertical scrolling through the hours is unchanged; with reduced motion it jumps instead of gliding. |

`qa/compact_header.cjs` measures the visible hours with the switch off and on at 320, 390, 700 and
1280 px and checks every header control stays fully on screen. `qa/trackpad_swipe.cjs` sends real
wheel events (switch off and on, Week and Day, long swipes, vertical scroll, Shift + wheel, reduced motion).

Run `python3 qa/headless.py` for the stdlib suites (data init, worker, Connected accounts
sync with a fake provider, iCal parsing/sources/HTTP, coexistence, API). `qa/sync.py` is the
fake-provider contract suite (no real Google account). `qa/thales_sync.py` is the disposable
worker runner for API/browser and the actual Runtipi Compose recipe plus a fake provider on
the same Docker network.

## QA and evidence boundaries

`python3 qa/api.py --url http://127.0.0.1:18787` is destructive **test-data-only QA**.
Run only against a new disposable volume. `qa/ical.py`, `qa/ical_sources.py` and
`qa/http_ical.py` use synthetic feeds to cover URL boundaries, proxy/redirect refusal,
recurrence parsing, secret redaction, persistence, rollback, sync and source removal;
`qa/coexist.py` proves iCal subscriptions and Connected accounts sync keep each other's data.
`qa/ical_browser.cjs` covers owner-facing Add calendar, Sync now and Remove at phone and
desktop widths in light and dark. `qa/browser.cjs` tests real Chrome, UI import, views, Back
and the Connected accounts Settings section with the separately fetched shared client.
`qa/hosted.cjs` uses the real pinned shared services/Appearance implementations in a labelled
test registry/iframe harness. It is not the full production shell, a physical iPhone/Android,
or live Google-account proof. Node QA needs the pinned dependency in `qa/package.json`, a
Chromium-family browser and writable scratch space. `python3 qa/headless.py` is the fast
stdlib-only suite. `qa/container_release.py` delegates to the native-architecture release
runner.
