---
wizard: 0.2
id: wizard-calendar
name: Calendar
type: view
category: app
version: 0.2.0
summary: Your Google and Microsoft calendars in one view. Add, edit and answer invites; private iCal links and snapshots too.
license: MIT
source: https://github.com/humanitylabs-org/wizard-calendar
runtime:
  package: source
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8799
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8799
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8799
  source:
    path: web
    build: python3 tools/check_view.py
    dist: web
provides: [calendar-viewing, calendar-import, calendar]
system: false
uses: [mail-calendar, wizard-google, wizard-microsoft]
needs: []
health: /healthz
---

# Calendar — private test release

Empty by default; the first screen offers Connect Google / Connect Microsoft. Connecting runs inside Calendar
(web/connect.js, the same sheet as Wizard Mail): Quick connect through Composio in one window, or your own app in the
Google / Microsoft app. Connected calendars are read and changed through those apps' box-only
`wizard.mail-calendar/1` API (Calendar never holds a sign-in): Day / Week / Month, add, edit, delete, answer invites.
Owners can still add a private Google iCal link in Settings; Calendar stores it locally, refreshes a read-only
snapshot and never writes iCal or snapshot events. The API and MCP
expose only the redacted visible state. See OSCAR-SETUP.md for privacy and snapshot contracts.
The Wizard gateway must serve its approved shared app-client.js resource. A standalone
install uses tools/run_portable.py without an app image build. Not a public store listing.
