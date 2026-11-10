# Calendar — private test release 0.1.0

Day, Week and Month views of read-only calendars. **Fresh installs are empty.**
The owner can add a private Google iCal link in Settings; Calendar stores it locally,
refreshes the feed, and never creates or edits provider events. The sample under `fixtures/`
is synthetic and is never imported automatically. A private iCal link is a bearer secret:
keep the data volume and backups private, and never paste the link into chat or logs.
Advanced snapshot import and operator-managed connectors remain available; see
[OSCAR-SETUP.md](OSCAR-SETUP.md).

## Install independently — no app image build

Prerequisites: Docker with Compose v2, Python 3.10+, network access for the pinned Python
base image and shared WizardApp client. No other running apps or Google account needed.
Extract the source release or clone this private repository at its exact test-release tag.
Then:

```sh
python3 tools/run_portable.py start
curl --fail http://127.0.0.1:18787/healthz
curl --fail http://127.0.0.1:18787/api/events
```

Open **http://127.0.0.1:18787/**. It must say “No calendar yet.” Both events and calendars
must be empty. The helper runs the same source recipe on a pinned public Python base
image: no unpublished app image and no compiler/build toolchain are needed. It copies
runtime source into a content-addressed named volume mounted read-only at `/app`.
It separately fetches the approved shared client, verifies its SHA256, and installs it in
an app-specific core volume. It creates writable app-data owned by UID/GID 1000. These
volumes work with Docker Desktop, Linux Docker or a VM-backed Colima daemon.
No host source/data/keyring directories are mounted. The managed runtime retains the
source recipe's root user with all capabilities dropped, read-only root/source and
no-new-privileges. No provider connector is started.

Custom instance: `python3 tools/run_portable.py start --project calendar-personal --port 18788`.
For architecture rehearsal add `--platform linux/arm64` or `--platform linux/amd64`.
Use the same project name for restart, updates and removal; it identifies the retained data.
The helper binds loopback only and sets exact matching Host and Origin allowlists. These
are not caller authentication: never expose this single-owner service directly to a LAN
or Internet. Remote Wizard access must go through its authenticated gateway.

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
# After checking out/extracting a newer approved source release:
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
host migration. The service never seeds, resets or migrates another installation. Saved iCal
sources refresh periodically after startup; a fresh install makes no Google requests.

## Wizard package / developer option

`wizard.md`, `runtipi/config.json`, portable `runtipi/docker-compose.yml`, `openapi.json`
and `skill/SKILL.md` form the independently installable Wizard package. `runtime.package: source`
runs the pinned official multi-architecture Python image with `${APP_SOURCE_DIR}:/app:ro`;
there is no custom image, build or embedded source payload. The App Manager must supply
`APP_SOURCE_DIR` (wizard-app-manager#153); older App Managers cannot install this recipe.
The managed service runs as root with all capabilities dropped so root-owned app-data
binds remain writable, retaining read-only root/source and no-new-privileges. Pass its exact
trusted hosts/origins. `python3 tools/package_runtime.py --check` verifies recipe generation.
The Dockerfile and root `compose.yml` remain optional standalone development tools.
Wizard must provide the shared core URL and attach the iframe via its shared app services.
Catalog admission is a separate platform/release-owner step.
No application image registry publication or custom image archive is required.

API: `GET /healthz`, `GET /api/events`, `GET /api/export`, `POST /api/import`,
`POST /api/calendars/visibility`, redacted `GET /api/sources`, `POST /api/sources`,
`POST /api/sources/remove`, and `POST /api/sync`. MCP: `POST /mcp`, tool
`calendar_events` (read-only). The same routes work beneath `/wizard-calendar/`.
See OSCAR-SETUP.md for source restrictions, privacy boundaries and full input limits.

## QA and evidence boundaries

`python3 qa/api.py --url http://127.0.0.1:18787` is destructive **test-data-only QA**.
Run only against a new disposable volume. `qa/ical.py`, `qa/ical_sources.py` and
`qa/http_ical.py` use synthetic feeds to cover URL boundaries, proxy/redirect refusal,
recurrence parsing, secret redaction, persistence, rollback, sync and source removal.
`qa/ical_browser.cjs` covers owner-facing Add calendar, Sync now and Remove at phone and
desktop widths in light and dark. `qa/browser.cjs` retains the existing UI import, view,
visibility and Back coverage. `qa/hosted.cjs` uses the real pinned shared services/Appearance
implementations in a labelled test registry/iframe harness. It is not the full production
shell, a physical iPhone/Android, or live Google-account proof. Node QA needs the pinned
dependency in `qa/package.json`, a Chromium-family browser and writable scratch space.
`qa/container_release.py` is an optional image-build rehearsal, not part of the release's
required install path. The private release receipt records actual architectures, base-image
digest, checks, persistence evidence and remaining limitations.
