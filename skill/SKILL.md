---
name: calendar
description: Read calendar events and Connected accounts sync health; guide one-time Google setup.
---
# Calendar

Use MCP `calendar_events` for visible read-only events and `sync_status` for connection
state, linked accounts, last_success and errors. Always report freshness; never imply
that cached events are a live Google query. Neither read tool creates or edits events.

For a fresh installation open Connected accounts from Calendar. The owner brings their
own Google OAuth app once, connects accounts and permits read-only Calendar access there.
Read OSCAR-SETUP.md for setup and grant routing. Calendar holds no Google credentials.
Never reuse another owner's accounts/keys or ask for secrets in chat.

GET /api/sync reads health; POST /api/sync {} requests a background refresh (202), then
poll GET until syncing is false. Automatic sync runs at startup and every ten minutes
unless configured otherwise. Missing grant/endpoint means not_linked, not a crash.
Partial failures retain last-good events; inspect calendar_errors and last_error.

GET /api/export backs up all saved data, including hidden calendars and the last-good
per-calendar cache. Protect it privately. POST /api/import is an explicit legacy/manual
snapshot replacement; ask before overwriting owner data. Read export back and compare
contentSha256. The next linked automatic sync replaces manual data. Preserve the app-data
volume on upgrade/uninstall unless deletion was explicitly approved.
