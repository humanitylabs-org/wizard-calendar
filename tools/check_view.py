import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
for name in ('index.html', 'app.js', 'app.css', 'icon.svg'):
    assert (root / 'web' / name).is_file(), name
assert '/wizard-os-home/core/app-client.js' in (root / 'web/index.html').read_text()
assert 'WizardApp.back.push' in (root / 'web/app.js').read_text()
import re
# An app with an owner-facing screen is an app, not a screenless agent app.
assert re.search(r'^type:\s*view$', (root / 'wizard.md').read_text(), re.M), 'wizard.md must declare the owner-facing view'
assert json.loads((root / 'runtipi/config.json').read_text())['wizard_type'] == 'view', 'Runtipi must project Calendar as a view'
# Design rules v0, rule 1: the app frame fills its window (no width cap).
assert not re.search(r'^\.app \{[^}]*max-width', (root / 'web/app.css').read_text(), re.M), '.app must not cap its width'
print('View source complete; no build transform required')
