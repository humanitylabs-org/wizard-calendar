---
name: calendar
description: Read calendar events and sync health; guide Connected accounts or private Google iCal setup.
---
# Calendar

Use MCP `calendar_events` for visible read-only events and `sync_status` for Connected
accounts connection state, linked accounts, last_success and errors. Always report
freshness (`syncedAt`, `syncError`, per-source errors); never imply that cached events are a
live Google query. Neither read tool creates, edits, deletes or RSVPs to events.

Two sources feed the same calendar, and they coexist:

1. **Connected accounts** (Google OAuth). The owner brings their own Google OAuth app once,
   connects accounts and permits read-only Calendar access in Connected accounts. Read
   OSCAR-SETUP.md for setup and grant routing. Calendar holds no Google credentials. A
   missing grant/endpoint means not_linked, not a crash.
2. **Private Google iCal links.** Calendar → Settings → Add calendar with Google's **Secret
   address in iCal format**. That URL is a bearer secret: never ask the owner to paste it
   into chat, never repeat it, and never place it in logs or task output. Direct them to the
   owner-facing Calendar screen instead.

Never reuse another owner's accounts, feeds or keys, or ask for secrets in chat.

GET /api/sync reads Connected accounts health; POST /api/sync {} refreshes iCal links and
requests a background Connected accounts refresh (202, then poll GET until syncing is false;
200 when only iCal links exist). Automatic Connected accounts sync runs at startup and every
ten minutes unless configured otherwise; iCal links refresh every 15 minutes by default.
Partial failures retain last-good events; inspect calendar_errors and last_error.

GET /api/export backs up normalized events, hidden calendars and the last-good per-calendar
cache; it deliberately excludes private iCal links. Protect it privately. POST /api/import
is an explicit manual snapshot replacement; ask before overwriting owner data and read the
export back to compare contentSha256. Saved iCal sources remain and return on the next
refresh; the next linked Connected accounts sync replaces manual data. Preserve the app-data
volume on upgrade or uninstall unless deletion was explicitly approved; it contains the
private iCal source configuration.
