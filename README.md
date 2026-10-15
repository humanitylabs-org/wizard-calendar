# Calendar — private test release 0.1.0

Day, Week and Month views of a read-only calendar snapshot. **Fresh installs are empty.**
No accounts, events, contacts, tokens, keyrings or live connector config ship in this app.
The sample under `fixtures/` is synthetic and is never imported automatically.
The provider connector is intentionally operator-managed; see [OSCAR-SETUP.md](OSCAR-SETUP.md).

## Install independently (Docker Compose)

Prerequisites: Docker with Compose v2, Python 3.10+, network access for the Python base
image and pinned shared WizardApp client. No other running apps or Google account needed.
Clone this private repository at the release tag using your own GitHub access. Then:

```sh
python3 tools/fetch_core.py
docker compose -p calendar-test up -d --build
curl --fail http://127.0.0.1:18787/healthz
curl --fail http://127.0.0.1:18787/api/events
```

Open **http://127.0.0.1:18787/**. It must say “No calendar yet.” Both events and calendars
must be empty. The standalone server routes the separately downloaded, digest-verified
shared resource at `/wizard-os-home/core/app-client.js`; it is not an app-local replacement.
No public port is exposed. Host and Origin are exact allowlists, not caller authentication.
This single-owner local test server must not be exposed directly to a LAN or Internet.

If changing `CALENDAR_PORT`, also set `WIZARD_TRUSTED_HOSTS` and
`WIZARD_TRUSTED_ORIGINS` to match (for example `127.0.0.1:18788,localhost:18788` and
`http://127.0.0.1:18788,http://localhost:18788`). Add the exact authenticated gateway
host/origin when installed behind Wizard. Never use wildcard trust.

### Use a prebuilt private image instead

Download the matching `wizard-calendar-0.1.0-linux-arm64.tar.gz` or
`wizard-calendar-0.1.0-linux-amd64.tar.gz` from this repository's private test release.
Verify its SHA256 against the release receipt, then (example: arm64):

```sh
docker load -i wizard-calendar-0.1.0-linux-arm64.tar.gz
python3 tools/fetch_core.py
CALENDAR_IMAGE=wizard-calendar-test:0.1.0-arm64 docker compose -p calendar-test up -d --no-build
```

The images are release assets, not published to a registry. `images.json` distinguishes
Docker image IDs from registry digests and gives archive SHA256 values for both architectures.
The portable Runtipi payload needs only its pinned public Python base, not these image assets.

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

Restore a genuinely empty test instance by importing `fixtures/empty.json` with the same
command or file picker. This replaces imported data; only do it on the disposable test instance.
Never clear someone's actual calendar snapshot without permission.

## Update, backup, remove

```sh
curl --fail http://127.0.0.1:18787/api/export -o calendar-backup.json
# After checking out a newer approved release:
python3 tools/fetch_core.py
docker compose -p calendar-test up -d --build --force-recreate
curl --fail http://127.0.0.1:18787/api/export
# Stop/remove the service but retain the named data volume:
docker compose -p calendar-test down
```

Keep the same Compose project name for updates and reinstallation. `down -v` destroys the
snapshot; do not use it for upgrades. Backups contain private calendar information.
Importing a backup preserves events; visibility preferences live in the retained data volume.
The server never seeds, resets, migrates another installation or invokes Google on startup.

## Wizard package

`wizard.md`, `runtipi/config.json`, portable `runtipi/docker-compose.yml`, `openapi.json`
and `skill/SKILL.md` form the independently installable Wizard package. The inline Compose
payload is the exact runtime source, not an external unpublished app image. Runtipi must
create writable app-data owned by UID/GID 1000 and pass its exact trusted hosts/origins.
Wizard must provide the shared core URL and attach the iframe via its shared app services.
Private catalog admission is a platform/release-owner step, not a public listing.

API: `GET /healthz`, `GET /api/events`, `GET /api/export`, `POST /api/import`,
`POST /api/calendars/visibility`. MCP: `POST /mcp`, tool `calendar_events` (read-only).
The service also accepts the same routes beneath `/wizard-calendar/`.

## QA

`python3 qa/api.py --url http://127.0.0.1:18787` is destructive **test-data-only QA**.
Run only against a new disposable volume. `qa/browser.cjs` exercises UI import, views and Back
with the real separately fetched shared client. See the private release receipt for execution
host, immutable commit, image identities, architecture evidence and remaining limitations.
