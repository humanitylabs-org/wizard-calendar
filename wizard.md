---
wizard: 0.2
id: wizard-calendar
name: Calendar
type: view
category: app
version: 0.1.0
summary: Read-only calendar views with private Google iCal subscriptions and snapshot import.
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
provides: [calendar-viewing, calendar-import]
system: false
uses: []
needs: []
health: /healthz
---

# Calendar — private test release

Empty by default. Owners add a private Google iCal link in Settings; Calendar stores it
locally, refreshes a read-only snapshot and never writes provider events. The API and MCP
expose only the redacted visible state. See OSCAR-SETUP.md for privacy and snapshot contracts.
The Wizard gateway must serve its approved shared app-client.js resource. A standalone
install uses tools/run_portable.py without an app image build. Not a public store listing.
