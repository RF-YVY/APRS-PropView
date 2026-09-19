import re
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


class _SettingsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.div_stack = []
        self.section_stack = []
        self.ids = []
        self.section_keys = []
        self.control_sections = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        started_section = None
        if tag == "div":
            classes = set(values.get("class", "").split())
            if "settings-section" in classes:
                started_section = values.get("data-settings-key")
                self.section_stack.append(started_section)
                self.section_keys.append(started_section)
            self.div_stack.append(started_section)
        control_id = values.get("id")
        if control_id:
            self.ids.append(control_id)
            if self.section_stack:
                self.control_sections[control_id] = self.section_stack[-1]

    def handle_endtag(self, tag):
        if tag != "div" or not self.div_stack:
            return
        started_section = self.div_stack.pop()
        if started_section is not None:
            self.section_stack.pop()


class SettingsStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).parents[1] / "static" / "index.html").read_text(encoding="utf-8")
        cls.parser = _SettingsParser()
        cls.parser.feed(cls.html)

    def test_ids_and_settings_section_keys_are_unique(self):
        duplicate_ids = [value for value, count in Counter(self.parser.ids).items() if count > 1]
        duplicate_sections = [value for value, count in Counter(self.parser.section_keys).items() if count > 1]
        self.assertEqual(duplicate_ids, [])
        self.assertEqual(duplicate_sections, [])

    def test_lightning_controls_have_one_alerts_weather_home(self):
        lightning_controls = [
            value for value in self.parser.control_sections
            if "lightning" in value or value.startswith("cfg-watched-alert-")
        ]
        self.assertTrue(lightning_controls)
        for control_id in lightning_controls:
            self.assertIn(self.parser.control_sections[control_id], {"weather", "watched-alerts"}, control_id)

    def test_space_weather_controls_live_with_propagation(self):
        space_controls = [value for value in self.parser.control_sections if value.startswith("cfg-space-weather-")]
        self.assertTrue(space_controls)
        for control_id in space_controls:
            self.assertEqual(self.parser.control_sections[control_id], "propagation", control_id)

    def test_every_settings_label_targets_an_existing_unique_id(self):
        ids = set(self.parser.ids)
        label_targets = re.findall(r'<label\b[^>]*\bfor="([^"]+)"', self.html, flags=re.IGNORECASE)
        missing = sorted(set(label_targets) - ids)
        self.assertEqual(missing, [])

    def test_club_display_uses_full_width_auto_scrolling_dashboards(self):
        root = Path(__file__).parents[1]
        kiosk_js = (root / "static" / "js" / "kiosk.js").read_text(encoding="utf-8")
        styles = (root / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn("scrollTarget: '#tab-prop .prop-detail'", kiosk_js)
        self.assertIn("scrollTarget: '#tab-analytics .analytics-panel'", kiosk_js)
        self.assertIn("function beginAutoScroll", kiosk_js)
        self.assertIn("'longest-paths':", kiosk_js)
        self.assertIn("heatmap:", kiosk_js)
        self.assertIn("packets:", kiosk_js)
        self.assertIn('not([data-kiosk-scene="map"]) #map-panel', styles)
        self.assertIn('[data-kiosk-scene="map"] #side-panel { display: none; }', styles)
        self.assertIn("height: auto !important", styles)

    def test_shared_ui_polish_controls_are_present(self):
        root = Path(__file__).parents[1]
        app_js = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")
        themes = (root / "static" / "css" / "themes.css").read_text(encoding="utf-8")

        self.assertIn('id="btn-header-details"', self.html)
        self.assertEqual(self.html.count('class="map-control-group"'), 4)
        self.assertIn('id="cfg-ui-density"', self.html)
        self.assertEqual(self.html.count('data-dashboard-panel="'), 6)
        self.assertEqual(app_js.count('data-settings-task="'), 6)
        self.assertIn("function initDashboardPanelPreferences", app_js)
        self.assertIn("function initGuidedEmptyStates", app_js)
        self.assertIn(':root[data-ui-density="comfortable"]', themes)
        self.assertIn(':root[data-ui-density="wallboard"]', themes)

    def test_source_health_card_uses_top_level_overlay(self):
        root = Path(__file__).parents[1]
        source_health = (root / "static" / "js" / "source-health.js").read_text(encoding="utf-8")
        styles = (root / "static" / "css" / "style.css").read_text(encoding="utf-8")

        self.assertIn("document.body.appendChild(panel)", source_health)
        self.assertIn("!control.contains(event.target) && !panel.contains(event.target)", source_health)
        self.assertRegex(styles, r"\.source-health-panel\s*\{[^}]*z-index:\s*30000",)


if __name__ == "__main__":
    unittest.main()
