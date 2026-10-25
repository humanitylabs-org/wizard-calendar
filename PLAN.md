# Connected accounts sync

Reuse:
- REUSE WizardApp app-client.js Back stack and live theme; retain packaged Day/Week/Month, Today and Settings gear (already match the read-only live copy).
- REUSE validate()/save() atomic snapshot import path for every provider snapshot.
- EXTEND candidate: WizardApp.nav has no openApp; use provider setup_url with target=_top. No shell changes.
- EXTEND Calendar domain worker, sync diagnostics and Settings; no OAuth or shell implementation in Calendar.

Acceptance: stdlib fake-provider tests, API regression, Thales browser matrix (phone/desktop, light/dark), actual source-package Runtipi Compose + fake provider/header proof. Public branch and PR only; no owner service writes. Backend timezone UTC unless configured, UI browser timezone unless configured.

## Legacy parity restoration
Source of truth: the supplied live legacy tree, including its dirty view changes (read-only).
Reuse:
- appearance: REUSE WizardApp.theme and --wz-* roles; EXTEND the Calendar domain adapter wizard-appearance.js with the live skin calendar palette (no theme storage or transport).
- Back: REUSE WizardApp.back.push for event/Settings overlays. Day/Week/Month are peer tabs, not nested history views; switching tabs adds no Back steps.
- OAuth: REUSE Connected accounts. Legacy manual gog start/finish endpoints explicitly return 410 with setup_url, superseded_by and an explanation; no credentials are accepted.
- QA: EXTEND the live qa, qa_geometry and qa_views suites to disposable synthetic snapshots, portable paths and the shared Appearance host; preserve their view/geometry/Back assertions.
Visual: compare live-derived layout and candidate screenshots in the private parity receipt. No live deployment or merge.
