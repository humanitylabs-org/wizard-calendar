# Calendar 0.3.0 — release note

## Package contract

- `runtime.package: image`; both services use the public multi-arch (linux/amd64 +
  linux/arm64) image **`ghcr.io/humanitylabs-org/wizard-calendar:sha-<commit>@sha256:<digest>`**,
  pinned by digest and built from this repo by `.github/workflows/app-image.yml`
  (the shared `wizard-app-index` workflow, native runners). The image carries
  `org.opencontainers.image.revision=<commit>`. There is no `/app` source bind,
  `build:` or `pull_policy: never`. After changing `app/`, `web/` or `openapi.json`,
  rebuild the image, then update `IMAGE` in `tools/package_runtime.py` and regenerate
  `runtipi/docker-compose.yml` with it.
- `app/Dockerfile`: Python 3.12 slim Bookworm, explicit tzdata, baked app/web/OpenAPI,
  default user **1000:1000**, HTTP `/healthz` healthcheck. No provider credentials.
- Managed state: **`${APP_DATA_DIR}/data:/data`**. A fresh Docker bind is root-owned:
  `calendar-data-init` is an offline, one-shot root service with only **CHOWN**.
  It opens `/data` without following links and changes only its directory owner.
  The main service waits for successful completion, stays **1000:1000**, adds no
  capabilities, drops ALL, has a read-only root, no-new-privileges, memory bound,
  and `/tmp:rw,noexec,nosuid,size=16m`. A pre-existing unwritable data root fails;
  no recursive data migration is attempted.
- The only form field (timezone) is optional with default `""`. No box hostname,
  provider URL, account, client key, shared-core path, or grant secret is required
  on the install form. Empty timezone uses UTC for sync and browser timezone for UI.
- Gateway path stays **`/wizard-calendar/`**. `Handler.route` accepts that prefix
  and unprefixed paths. Manifest `view.path: /` is the upstream root, not a new
  gateway URL. WAM generates fresh-host allowlists. Without an explicit Origin
  list, only HTTP/HTTPS Origins matching the already-validated Host are accepted;
  `Sec-Fetch-Site: cross-site` and unknown Hosts remain rejected.

## Fresh Calendar → Connected accounts grant

The manifest declares **`uses: [connected-accounts]`**, not `requires.services`
(which requests the AI connection router). The provider advertises `calendar-source`;
Calendar still accepts existing `wizard-connectors` and `slot:calendar-source`
credentials/endpoints for compatibility. Only the renamed provider id is a new
install default: no duplicate grants, no provider hostname guess.

Source inspection, not a live-install claim: WAM checkout **247cc12a2d1525fa51eab9b28d0e56cc8e62957d**,
`packages/backend/src/modules/docker/`:

1. `wizard-app-grants.ts:14–33`: `targets()` converts `uses` into a consumer/provider
   grant; when `connected-accounts` is installed its exact id is retained.
   `providers()` matches the id or an explicitly declared slot. Proposals only
   appear when a provider is available.
2. `wizard-storage.ts:310–348`: the install proposal endpoint also reads the
   materialized candidate and direct `uses` dependency recipe. Thus it can offer
   this edge before Calendar itself is running. `docs/APP_STATE_AND_SHARES.md:66–78`
   documents proposals and canonical `<dataDir>/state/wizard-grants.json`.
3. `wizard-app-grants.ts:120–209`: current connection policy automatically creates
   the declared grant as **`approved: install`** when both apps are present.
   A sensitive target becomes pending; an owner denial is sticky. Provider-later
   installation is handled on the next reconciliation. Older proposal-based
   versions may require the owner to keep/approve the proposed install permission.
4. `wizard-app-grants.ts:403–420,444–509`: reconciliation writes the consumer's
   app-data `wizard/grants.json`, creates/reuses the outgoing key under
   `connected-accounts`, supplies `provider_endpoints["connected-accounts"]` from
   the provider's main service, and writes a SHA-256 incoming row for caller
   `wizard-calendar` into the provider's file before publishing the consumer key.
5. `wizard-app-grants.ts:272–294` and `builders/compose.builder.ts:216`: WAM injects
   `${APP_DATA_DIR}/wizard:/wizard:ro` plus `WIZARD_GRANTS_FILE=/wizard/grants.json`.
   The recipe must not manufacture a second grants mount or hand-written key.

**Owner action:** install Connected accounts if not installed; configure their
Google OAuth app there, sign in, consent to read-only Calendar scope, and explicitly
allow Calendar for each account. On current normal fresh-box policy no manual key,
file edit, or extra app-grant approval is needed. If Connected accounts is marked
sensitive, approve the pending Calendar connection in **App Manager → Connections**;
if disconnected/denied, explicitly reconnect it. Google consent/per-account access
is separate from the app-to-app grant and is never auto-granted by this package.

The local installed provider recipe (read-only reference) confirms
`id: connected-accounts`, `renamed_from: [wizard-connectors]`, and
`provides: [..., calendar-source]`. Its older documented service alias is not used
as a Calendar default. Provider-supplied `setup_url` remains authoritative; the
legacy `/wizard-connectors/` fallback is intentionally retained for its gateway alias.

## Local release runner (optional smoke test)

Canonical source: `tools/alpha_runner.py`; `qa/container_release.py` delegates to it.
Stage a clean committed checkout as cwd and set **ARCH=amd64|arm64** and optional
**DOCKER_CMD** (default `docker`; use `docker --context colima` on an ARM Mac worker).
The runner refuses an architecture different from the daemon's native architecture.
It does not submit jobs, push images, create tags/releases, or deploy anything.

It runs `qa/headless.py`, builds with
`org.opencontainers.image.revision=<git HEAD>`, validates image architecture/user,
then smokes an isolated no-copy data volume through the same CHOWN-only init and
hardened non-root service. It requires HTTP 200 on the prefixed health endpoint,
all four `/proc/1/status` Uid/Gid values to equal 1000, writable `/data`, empty events,
and the real Docker healthcheck to become healthy. Only its uniquely named smoke
container/volume are removed. Export is `docker save | gzip -n`, with both process
statuses checked and atomic archive promotion.

Outputs:
- `wizard-calendar-<arch>.tar.gz`
- `evidence/headless-<arch>.log`
- `evidence/release-<arch>.json`: commit/version/arch, SHA-256, bytes, image id/tag,
  health/uid/gid evidence and `live_provider: false`.

## What is and is not verified

`python3 qa/headless.py` runs offline recipe/version/security checks, real local
HTTP API tests, sync fake-provider tests, connector adapter fixtures, same-host
Origin defaults, and view-source presence. Everything uses disposable local state;
no browser, running app, owner data, OAuth service, or Docker is touched.

Version agreement is enforced across wizard.md, Runtipi config, the developer Compose
image name, server VERSION, OpenAPI, and shared-client ready metadata.
The owner-specific text scan permits only reserved synthetic example email domains.

**Not covered by the release checks:** the local runner's container smoke, a fresh-box
Store install with actual WAM, two-skin browser regression, and owner Google consent.
None ran in this release-preparation change. The existing provider-field parity prerequisite in PARITY.md remains;
headless synthetic-provider success is not proof of live Google field completeness.
