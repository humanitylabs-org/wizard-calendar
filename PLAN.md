# Connected accounts sync

Reuse:
- REUSE WizardApp app-client.js Back stack and live theme; retain packaged Day/Week/Month, Today and Settings gear (already match the read-only live copy).
- REUSE validate()/save() atomic snapshot import path for every provider snapshot.
- EXTEND candidate: WizardApp.nav has no openApp; use provider setup_url with target=_top. No shell changes.
- EXTEND Calendar domain worker, sync diagnostics and Settings; no OAuth or shell implementation in Calendar.

Acceptance: stdlib fake-provider tests, API regression, Thales browser matrix (phone/desktop, light/dark), actual source-package Runtipi Compose + fake provider/header proof. Public branch and PR only; no owner service writes. Backend timezone UTC unless configured, UI browser timezone unless configured. Google color retained; palette is the skin-token fallback.
