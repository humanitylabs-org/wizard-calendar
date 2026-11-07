---
wizard: 0.2
id: wizard-calendar
name: Calendar
type: service
category: app
version: 0.3.0
summary: Read-only calendar views synced through Connected accounts; bring your own Google OAuth app once.
license: MIT
source: https://github.com/humanitylabs-org/wizard-calendar
runtime:
  package: image
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
provides: [calendar-viewing, calendar-import, calendar-sync]
system: false
uses: [connected-accounts]
needs: []
health: /healthz
---

# Calendar

Empty by default. No provider credentials or account configuration are included.
API and MCP read a local snapshot; provider authorization happens outside this app.
See OSCAR-SETUP.md for Connected accounts setup, grant routing and the manual snapshot contract.
The Wizard gateway must serve its approved shared app-client.js resource. A standalone
install uses tools/run_portable.py with the already-pulled image.
The default gateway path is /wizard-calendar/ (the server accepts this prefix and /).
See RELEASE.md for image packaging, grant policy and verification boundaries.
