---
name: calendar
description: Read visible calendar events or guide the owner through adding a private Google iCal source.
---
# Calendar

Use the installed `calendar_events` MCP tool to read the visible read-only calendar state.
It cannot create, edit, delete or RSVP to provider events. Report `syncedAt` and any source
errors rather than implying every event is live.

Fresh installs start empty. The normal owner setup is Calendar → Settings → Add calendar
with Google's **Secret address in iCal format**. That URL is a bearer secret: never ask the
owner to paste it into chat, never repeat it, and never place it in logs or task output. Direct
them to the owner-facing Calendar screen instead. Read OSCAR-SETUP.md from the source bundle
before configuring an operator-managed connector.

`GET /api/export` backs up normalized events and visibility but deliberately excludes private
iCal links. `POST /api/import` replaces the visible snapshot after validation; ask before
replacing user data. Saved iCal sources remain and return on the next refresh. Preserve the
app-data volume on upgrade or uninstall unless explicit deletion was approved; it contains
the private source configuration. Never reuse another person's account, feed or credentials.
