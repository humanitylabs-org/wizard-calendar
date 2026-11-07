# Live Calendar parity audit

## Current image baseline

The current release review compares exact tracked source at the supplied serving revision
`e9832184b9435d4fe67d15fe7bcee083ab65cf4c` against this branch, not an older gog branch
or GitHub main. The archived-source lexical gate reports no removed labels, routes,
modules or tests, with no waivers. Review of the source delta finds no removed live UI
or API capability: Day/Week/Month, details/actions, navigation, settings/visibility,
sync/cache/error handling, snapshot/preferences import/export and MCP remain. The
manual-link 410 responses and shared-theme migration described below already existed
in that serving revision; they are not new image-package feature drops.

Runtime source binds/hot-editing are intentionally replaced by fixed image packaging;
they are not an owner-facing Calendar feature. The root-only data initializer grants
only CHOWN, has no network and changes only the data-root ownership, not its contents.
Browser/Compose/image tests and an actual in-shell two-skin review remain separate
gates; a lexical PASS is not visual or installed-runtime acceptance. No deployment or
owner-data migration is authorized by this document.

The earlier rendered/legacy audit below is historical supporting evidence, not a
substitute for the current serving-source comparison.

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
| Manual gog linking `/api/connect/start`, `/api/connect/finish` | **Superseded by Connected accounts**. Both real GET/POST routes return 410 with message, `setup_url: /connected-accounts/`, `superseded_by: Connected accounts`. Calendar accepts no credential/callback exchange. API suite tests both prefixed/unprefixed routes and origin rejection. No waiver or pretend OAuth implementation. |
| `/api` | Legacy only matched a static/API prefix; candidate adds a real JSON route index with supersession metadata. |
| Manifest/capture resource | No Calendar capture feature existed. App-owned manifest removed in favor of shared shell installation policy; unrelated capture script not loaded. No service worker or root-exit implementation added. |
| Legacy QA suites | `qa.cjs`, `qa_geometry.cjs`, `qa_views.cjs` ported, not empty filenames. Personal data/host/path assumptions replaced with disposable synthetic fixtures. Old gog assertions replaced by explained-410/Connected accounts checks. Old app-owned skin storage/Paper assertions replaced by shared-host live-theme tests (Paper is retired). |

Additional packaged features remain: validated atomic snapshot import/export, update hold through successful import/readback, MCP event/sync tools, portable runtime, explicit timezone, preferences import. No production data, route/tile, live unit or grant changes are part of this PR.

## Provider contract prerequisite (not waived)

The full source audit found losses beyond the lexical gate: the previous consumer dropped guest counts, provider descriptions and Meet URLs; used only -30/+180 days instead of the live -60/+400; and could not identify holiday palettes after hashing calendar IDs. This PR restores attendee-count validation/import/readback, description/Meet/UID/declined-response consumption, the full 460-day range split into two requests below the provider's 400-day cap, live title-or-UID+start dedupe, and holiday detection from provider_id.

**Do not claim full end-to-end cutover parity from a green lexical gate alone.** The older Connected accounts revision `91a491e` omitted event description, Meet URL, attendee count, iCalUID and self-response. The coordinated provider candidate now requests and emits bounded `description` (4000), `meet` (HTTPS, 2000), `attendee_count`, `ical_uid` and `self_response` without guest identities. Provider HTTP regressions verify these fields, and Calendar synthetic provider regressions verify consumption. Actual owner-authorized provider-to-Calendar sync remains an installed acceptance gate, not an approved feature drop.

The packaged freshness/status line is an intentional additive row, not a lost view. Standalone is always the dark fallback, including a light-preferring browser. Sheet/close-bar surfaces flatten translucent shared overlay colors over the shared base so underlying events do not bleed through.

## Commands

For an additional read-only rendered comparison, set `LEGACY_WEB_DIR` to a private copy of the actual legacy `web` directory. `qa/legacy-compare.cjs` injects only the same synthetic snapshot into that view, then compares exact titles, columns, month cell geometry, timed block placement/sizes, bottom tabs and event details/actions at phone and desktop widths. The original source and owner calendar data are never changed or contacted.

`app-parity-gate LIVE CANDIDATE --json` (no waivers).

On disposable Thales checkout with Colima running and scratch/mounts under `~/.cache`:

```
python3 qa/thales_sync.py
```

After pulling the published image, this runs unit/connector/API, standalone browser, desktop+phone pinned shared host, setup-card, all three ported legacy suites and actual image-recipe Compose/provider tests. `qa/container_release.py` now delegates to the native-only release runner; see RELEASE.md. Container/browser acceptance was not executed during source preparation.
