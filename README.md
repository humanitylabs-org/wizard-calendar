# Calendar — private test release 0.1.0

Day, Week and Month views of a read-only calendar snapshot. **Fresh installs are empty.**
No accounts, events, contacts, tokens, keyrings or live connector config ship in this app.
The sample under `fixtures/` is synthetic and is never imported automatically.
Provider setup is operator-managed: see [OSCAR-SETUP.md](OSCAR-SETUP.md).

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
must be empty. The helper runs the exact Runtipi inline source payload on a pinned public
Python base image: no unpublished app image and no compiler/build toolchain are needed.
It separately fetches the approved shared client, verifies its SHA256, and installs it in
an app-specific core volume. It creates writable app-data owned by UID/GID 1000. Both
volumes are named and work with Docker Desktop, Linux Docker or a VM-backed Colima daemon.
No host source/data/keyring directories are mounted. The runtime is non-root, read-only,
capability-dropped, with no-new-privileges. No provider connector is started.

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
The service never seeds, resets, migrates another installation or calls Google on startup.

## Wizard package / developer option

`wizard.md`, `runtipi/config.json`, portable `runtipi/docker-compose.yml`, `openapi.json`
and `skill/SKILL.md` form the independently installable Wizard package. The inline Compose
payload is exact runtime source. Its base image is pinned by multiarchitecture index digest.
Runtipi must create app-data owned by UID/GID 1000 and pass its exact trusted hosts/origins.
Wizard provides the shared core URL and attaches the iframe via shared app services.
Private catalog admission is the platform/release owner's step, not a public store listing.

`app/Dockerfile` and `compose.yml` also support a conventional developer image build.
Those are optional: the tested release/install path is the build-free portable package.
No application image registry publication or custom image archive is claimed for this release.

API: `GET /healthz`, `GET /api/events`, `GET /api/export`, `POST /api/import`,
`POST /api/calendars/visibility`. MCP: `POST /mcp`, tool `calendar_events` (read-only).
The same routes work beneath `/wizard-calendar/`. See OSCAR-SETUP.md for full input limits.

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
