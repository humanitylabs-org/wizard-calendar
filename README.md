# Calendar — private test release 0.1.0

Day, Week and Month views, synced in-app through **Connected accounts**. Fresh installs
start with **Connect your Google calendar**: bring your own Google OAuth app once in
Connected accounts, then authorize your accounts and read-only Calendar access there.
Calendar never stores Google credentials. See [OSCAR-SETUP.md](OSCAR-SETUP.md).
No accounts, events, contacts, tokens or live connector config ship in this app.
The sample under `fixtures/` is synthetic and is never imported automatically.

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

Open **http://127.0.0.1:18787/**. It must show “Connect your Google calendar.” Both events and calendars
must be empty. The helper runs the same source recipe on a pinned public Python base
image: no unpublished app image and no compiler/build toolchain are needed. It copies
runtime source into a content-addressed named volume mounted read-only at `/app`.
It separately fetches the approved shared client, verifies its SHA256, and installs it in
an app-specific core volume. It prepares writable app-data for the recipe user (root, with all capabilities dropped). These
volumes work with Docker Desktop, Linux Docker or a VM-backed Colima daemon.
No host source/data/keyring directories are mounted by the portable helper. The managed grants directory is mounted read-only. The managed runtime retains the
source recipe's root user with all capabilities dropped, read-only root/source and
no-new-privileges. No provider connector is started.

Custom instance: `python3 tools/run_portable.py start --project calendar-personal --port 18788`.
For architecture rehearsal add `--platform linux/arm64` or `--platform linux/amd64`.
Use the same project name for restart, updates and removal; it identifies the retained data.
The helper binds loopback only and sets exact matching Host and Origin allowlists. These
are not caller authentication: never expose this single-owner service directly to a LAN
or Internet. Remote Wizard access must go through its authenticated gateway.

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
or file picker. This replaces imported data, not provider events. Never clear an actual user
snapshot without permission. The source fixture is not loaded by the server on startup.

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
manually delete it on update. Backups contain private calendar information; store privately.
Importing a backup restores events; visibility preferences persist in the data volume.
The service never seeds, resets or migrates another installation. On startup it calls only the granted Connected accounts provider, never Google directly.

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

API: `GET /healthz`, `GET /api/health`, `GET /api/events`, `GET /api/export`,
`POST /api/import`, `POST /api/calendars/visibility`, `GET /api/sync`, `POST /api/sync {}`.
MCP: `POST /mcp`, read-only tools `calendar_events` and `sync_status`.
The same routes work beneath `/wizard-calendar/`. See OSCAR-SETUP.md for full input limits.
The App Manager injects its standard `${APP_DATA_DIR}/wizard:/wizard:ro` directory
and `WIZARD_GRANTS_FILE=/wizard/grants.json`; the recipe has no app-specific grant
mount. Code defaults to that path when the environment variable is absent and
fails closed on missing/invalid files. Wizard permissions must approve the
`wizard-calendar` → `wizard-connectors` edge. The provider endpoint from WAM takes
precedence over `CONNECTORS_URL`; no hand-written grant bridge is needed.
The source-package runtime has no inline source payload to regenerate; generate/check
its recipe with `tools/package_runtime.py` after runtime configuration changes.

The read-only live-copy comparison found Day/Week/Month, Today, gear, palette and shared
Back/theme already present in the package. They are retained, not replaced by legacy
OAuth callback forms, hardcoded owner zones, root history guards or local skin storage.
WizardApp.nav lacks openApp; setup uses provider `setup_url` with `target=_top` as an
EXTEND candidate. No wizard-ux/shell changes are included.

Run `python3 qa/sync.py` for the stdlib fake-provider contract suite (no real Google
account). `qa/thales_sync.py` is the disposable worker runner for API/browser and the
actual Runtipi Compose recipe plus a fake provider on the same Docker network.

## QA and evidence boundaries

`python3 qa/api.py --url http://127.0.0.1:18787` is destructive **test-data-only QA**.
Run only against a new disposable volume. `qa/browser.cjs` tests real Chrome, UI import,
views and Back with the separately fetched shared client. `qa/hosted.cjs` uses the real
pinned shared services/Appearance implementations in a labelled test registry/iframe harness.
It is not the full production shell, native iPhone/Android or live Google onboarding proof.
Node QA needs the pinned dependency in `qa/package.json`, Google Chrome and writable
external-disk scratch. `qa/container_release.py` is an optional image-build rehearsal, not
part of the release's required install path. The private release receipt records actual
architectures, base-image digest, checks, persistence evidence and remaining limitations.
