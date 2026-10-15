#!/usr/bin/env python3
"""Fetch the unmodified approved shared client for a standalone gateway."""
import hashlib
import urllib.request
from pathlib import Path
REV = '9a7bcc89f15cb733462d12e7c84bcade47cebc27'
SHA256 = 'fd6900e270e8e2d56354f5eef92d9e2b0095056f2280ebaa9e27151c0e1450b9'
url = f'https://raw.githubusercontent.com/humanitylabs-org/wizard-ux/{REV}/web/core/app-client.js'
with urllib.request.urlopen(url, timeout=30) as response: data = response.read()
assert hashlib.sha256(data).hexdigest() == SHA256, 'Shared client digest mismatch'
out = Path(__file__).resolve().parents[1] / '.runtime/core'
out.mkdir(parents=True, exist_ok=True)
(out / 'app-client.js').write_bytes(data)
print(f'Shared WizardApp resource verified at revision {REV}')
