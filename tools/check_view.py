from pathlib import Path
root = Path(__file__).resolve().parents[1]
for name in ('index.html', 'app.js', 'app.css', 'icon.svg'):
    assert (root / 'web' / name).is_file(), name
assert '/wizard-os-home/core/app-client.js' in (root / 'web/index.html').read_text()
assert 'WizardApp.back.push' in (root / 'web/app.js').read_text()
print('View source complete; no build transform required')
