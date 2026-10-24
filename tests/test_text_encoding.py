import unittest
from pathlib import Path
from scripts.check_text_encoding import check, SUSPECT


class TextEncodingTests(unittest.TestCase):
    def test_all_shipped_text_is_utf8_without_corruption(self):
        self.assertEqual(check(), [])

    def test_guard_catches_single_and_double_encoding_errors(self):
        for text in ('\u00e2\u0152\u201e', '\u00c3\u00a2\u00e2\u201a\u00ac', '\ufffd'):
            self.assertIsNotNone(SUSPECT.search(text))
        self.assertIsNone(SUSPECT.search('View \u2304 | \u00b0C | \u2192 | \U0001f4fb'))

    def test_toolbar_uses_encoding_independent_css_chevrons(self):
        root = Path(__file__).resolve().parents[1]
        css = (root / 'static/css/themes.css').read_text(encoding='utf-8')
        self.assertIn('content: "\\2304"', css)
        self.assertIn('content: "\\2303"', css)
