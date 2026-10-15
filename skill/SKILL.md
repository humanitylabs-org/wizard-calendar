---
name: calendar
description: Read imported calendar events or set up an explicitly authorized snapshot import.
---
# Calendar

Use the installed calendar_events MCP tool to read the visible snapshot. It cannot
create or edit provider events. Report the snapshot's syncedAt; do not imply it is live.
For a new install, explain that it starts empty. Read OSCAR-SETUP.md from the source
bundle before configuring a connector. Never reuse another user's accounts or keys.
GET /api/export backs up all imported events, including hidden calendars.
POST /api/import replaces the snapshot after validation; ask before replacing user data.
Read GET /api/export back and compare contentSha256 after import. Importing the same
snapshot is idempotent. Preserve the app-data volume on upgrade or uninstall unless
explicit deletion was approved. Connector scheduling and OAuth are operator-managed.
