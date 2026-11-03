#!/usr/bin/env python3
"""Bounded source checks, not browser/pixel acceptance; no git history needed.

Direct: python3 -B qa/test_calendar_style.py [--checker PATH --policy PATH]
The optional trusted-checker negative control skips under ordinary discovery
unless paths are supplied here or in WIZARD_STYLE_CHECKER/WIZARD_STYLE_POLICY.
"""
import argparse
import base64
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CHECKER = os.environ.get('WIZARD_STYLE_CHECKER')
POLICY = os.environ.get('WIZARD_STYLE_POLICY')
EVIDENCE_DIR = None


def rules(css):
    return {selector.strip(): body for selector, body in re.findall(
        r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    )}


class CalendarStyle(unittest.TestCase):
    def test_rem_values_at_default_root(self):
        css = (ROOT / 'web/app.css').read_text()
        # This document leaves html at the browser default. Each scoped rem
        # value preserves its prior pixel size at a 16px root, and scales when
        # the owner chooses larger text. Body font size is not the root size.
        expected_px = {
            '.hello h2': '22', '.hello p': '14.5',
            '.hello-row small, .wc-sheet .wz-main small': '12.5',
            '.hello-row .chev, .wc-sheet .chev': '20', '.hello .lnk': '13',
            '.sheet .chip-btn': '14', '.ev-form .check': '14.5',
            '.sheet select': '15', '.wc-sheet h2': '20',
            '.wc-sheet .muted': '14', '.wc-sheet .wc-note': '12.5',
            '.wc-sheet .wz-button': '14.5', '.wc-dot': '12',
        }
        current = rules(css)
        for selector, pixels in expected_px.items():
            value = re.search(r'font-size:\s*([\d.]+)rem', current[selector])
            self.assertIsNotNone(value, selector)
            assert value is not None
            self.assertEqual(Decimal(value[1]) * 16, Decimal(pixels), selector)

    def test_official_artwork_and_embedded_images_exact(self):
        current = (ROOT / 'web/settings.js').read_text()
        marks = current.split('  const MARKS = {', 1)[1].split('\n  };', 1)[0]
        embedded = dict(re.findall(r"(google|microsoft): 'data:image/svg\+xml;base64,([^']+)'", marks))
        expected = {
            'google': ('0 0 48 48', '4319d8ca13c75f97d8b083b9bf610941f7c12180cf93fdeaefb1c67fcd909032'),
            'microsoft': ('0 0 23 23', 'de3b92b16dd7787b22898ffd091684e7982731bca8bf22804d076061a592ebd2'),
        }
        self.assertEqual(set(embedded), set(expected))
        self.assertEqual(marks.count('data:image/'), 2)
        for name, (box, digest) in expected.items():
            asset = ROOT / f'web/content/{name}.svg'
            self.assertFalse(asset.is_symlink())
            raw = asset.read_bytes().strip()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
            self.assertEqual(base64.b64decode(embedded[name], validate=True), raw)
            svg = ET.fromstring(raw)
            self.assertEqual(svg.attrib, {'viewBox': box})
            self.assertEqual(svg.tag, '{http://www.w3.org/2000/svg}svg')
            self.assertEqual(len(svg), 4)
            self.assertTrue(all(p.tag == '{http://www.w3.org/2000/svg}path' and set(p.attrib) == {'fill', 'd'} for p in svg))

    def test_real_checker_content_scope_and_functional_negative(self):
        if not CHECKER or not POLICY:
            self.skipTest('Optional trusted checker/policy paths not supplied')
        spec = importlib.util.spec_from_file_location('pinned_style_checker', CHECKER)
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertIsNotNone(spec.loader)
        assert spec.loader is not None
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        policy = json.loads(Path(POLICY).read_text())
        self.assertIn('content', checker.SKIP)
        with tempfile.TemporaryDirectory(prefix='brand-scope-', dir=EVIDENCE_DIR) as tmp:
            root = Path(tmp)
            content = root / 'web/content'
            content.mkdir(parents=True)
            for name in ('google', 'microsoft'):
                raw = (ROOT / f'web/content/{name}.svg').read_bytes()
                (content / f'{name}.svg').write_bytes(raw)
                (root / f'web/{name}.svg').write_bytes(raw)
            (root / 'web/functional.css').write_text('.functional { color: rgb(1 2 3); }\n')
            (root / 'web/settings.js').write_text((ROOT / 'web/settings.js').read_text() + '\nconst negative = "color: rgb(1 2 3)";\n')
            findings = checker.scan(root, policy, strict=True)
            counts = {}
            for row in findings:
                self.assertTrue(row['error'])
                self.assertEqual(row['rule'], 'literal-colour')
                counts[row['path']] = counts.get(row['path'], 0) + 1
            self.assertEqual(counts, {'web/functional.css': 1, 'web/google.svg': 4, 'web/microsoft.svg': 4, 'web/settings.js': 1})

    def test_connect_sheet_shared_opaque_role_no_blur(self):
        css = (ROOT / 'web/app.css').read_text()
        sheet_rules = {k: v for k, v in rules(css).items() if '.wc-sheet' in k}
        panel = sheet_rules['.wc-sheet']
        self.assertIn('background: var(--wz-panel, color-mix(in srgb, var(--ink) 10%, var(--bg)));', panel)
        self.assertNotRegex(panel, r'opacity\s*:|transparent|--sheet|--wz-overlay')
        for body in sheet_rules.values():
            self.assertNotRegex(body, r'backdrop-filter|blur\(')
        self.assertIn('var(--wz-base, var(--bg)) 55%, transparent', sheet_rules['.wc-sheet::backdrop'])

    def test_brand_images_decorative_and_noninteractive(self):
        js = (ROOT / 'web/settings.js').read_text()
        self.assertIn("return el('img', null, 'wcs-mark', { src: MARKS[source], alt: '', 'aria-hidden': 'true' });", js)
        marker = rules((ROOT / 'web/app.css').read_text())['.wcs-mark']
        self.assertIn('width: 40px;', marker)
        self.assertIn('height: 40px;', marker)
        for declaration in ('pointer-events: none;', '-webkit-user-drag: none;', '-webkit-touch-callout: none;'):
            self.assertIn(declaration, marker)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--checker', default=CHECKER)
    parser.add_argument('--policy', default=POLICY)
    parser.add_argument('--evidence-dir', default=None)
    args, rest = parser.parse_known_args()
    CHECKER, POLICY, EVIDENCE_DIR = args.checker, args.policy, args.evidence_dir
    unittest.main(argv=[__file__, *rest])
