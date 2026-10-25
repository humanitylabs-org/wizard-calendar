# Live Calendar parity audit

This audit uses the supplied live tree, not GitHub main. The legacy tree is read-only; its dirty `web/app.js`, `index.html` and `wizard-appearance.js` are included in the comparison. No waivers are needed: the original `app-parity-gate` must pass with no missing inventory entries.

## Surface-by-surface comparison

| Live capability | Packaged treatment / executable coverage |
|---|---|
| Day, Week (default), Month; bottom tabs; persisted selected view | Retained implementation; `qa_views.cjs` tests default, placement, selected date, peer tabs and reload. Tabs are peers, not a nested router. |
| Monday-first month grid; today/selected geometry; month agenda | Same live grid, selection and agenda; `qa.cjs`, `qa_geometry.cjs` at 360/393/420/800. |
| Week/day time placement, overlaps, all-day multiday bars, now line/initial scroll | Same algorithms and CSS; `qa_views.cjs` uses fresh synthetic overlapping timed and all-day events. |
| Previous/next, title→today, numbered Today button, horizontal swipes | Existing handlers retained byte-for-byte apart from surrounding sync/import changes; view suite tests navigation and Today. |
| Event details: When, Calendar, Where, Guests, Notes, Meet/Map/Google links | Same event sheet markup and escaped data; month/view suites open details, close, backdrop and browser Back. |
| Settings gear, calendar counts/Hidden/Sync failed, visibility toggles | Restored exact `Sync failed` state plus escaped diagnostic, retained account-group structure where the provider supplies account metadata. Synthetic failure response tests state text; real fake-provider partial failures tested by sync/Compose suites. |
| Skin palette per calendar (not provider hex), holiday role | `web/wizard-appearance.js` is now an active domain adapter; uses `--k*`→`--wz-*`. Stored provider/owner preference colors remain unchanged in snapshots/API. Shared WizardApp exclusively owns theme transport/storage. |
| Live theme changes and hosted transparent canvas | Real pinned shared host/client tests Nebula/Grove × light/dark, phone/desktop, window/immersive, retained document/selected day/date/grid scroll/open sheet/scroll. Light scheme here is compatibility transport, not a claimed built-in light palette selector. |
| Back never exits | Shared `WizardApp.back.push` replaces legacy app history guard. Tests overlay close and peer Day+Settings flow; hosted root Back reports atRoot and keeps the frame open. Standalone first root Back stays with shared warning (shared browser core deliberately permits a repeated escape in a plain tab). |
| Google read-only multi-account periodic sync and Sync now | Connected accounts replaces gog subprocess/host credential storage. Synthetic provider and actual Compose regression cover accounts, grants, dedupe, hidden calendars, last-good partial failure, retry/rotation/revoke. Real owner consent is not automated by these suites. |
| Manual gog linking `/api/connect/start`, `/api/connect/finish` | **Superseded by Connected accounts**. Both real GET/POST routes return 410 with message, `setup_url: /wizard-connectors/`, `superseded_by: Connected accounts`. Calendar accepts no credential/callback exchange. API suite tests both prefixed/unprefixed routes and origin rejection. No waiver or pretend OAuth implementation. |
| `/api` | Legacy only matched a static/API prefix; candidate adds a real JSON route index with supersession metadata. |
| Manifest/capture resource | No Calendar capture feature existed. App-owned manifest removed in favor of shared shell installation policy; unrelated capture script not loaded. No service worker or root-exit implementation added. |
| Legacy QA suites | `qa.cjs`, `qa_geometry.cjs`, `qa_views.cjs` ported, not empty filenames. Personal data/host/path assumptions replaced with disposable synthetic fixtures. Old gog assertions replaced by explained-410/Connected accounts checks. Old app-owned skin storage/Paper assertions replaced by shared-host live-theme tests (Paper is retired). |

Additional packaged features remain: validated atomic snapshot import/export, update hold through successful import/readback, MCP event/sync tools, portable runtime, explicit timezone, preferences import. No production data, route/tile, live unit or grant changes are part of this PR.

## Commands

`app-parity-gate LIVE CANDIDATE --json` (no waivers).

On disposable Thales checkout with Colima running and scratch/mounts under `~/.cache`:

```
python3 qa/thales_sync.py
```

This runs unit/connector/API, standalone browser, desktop+phone pinned shared host, setup-card, all three ported legacy suites and actual source-package Compose/provider tests. `qa/container_release.py` is a historical dual-architecture image export tool pinned to a previous release branch, not a source-package regression suite and is not used for this cutover.
