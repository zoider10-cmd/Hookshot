"""gpu/vk/menu_i18n.h, the Insert menu's translations: every table's texts are the menu's own (vk_menu.cpp writes each
English text), every translation keeps its text's printf conversions in order and its leading and trailing spaces (the menu
joins pieces), and the language list holds what vk_menu_i18n.cpp expects. The controls and Automatic prompt hints
must remain present in every translated table. No game, no compiler.

Run with: python -I tests/test_menu_i18n.py
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def c_strings(text):
    """The C string literals of a source, adjacent ones joined, escapes as written"""
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'"\s*\n\s*"', '', text)
    return re.findall(r'"((?:[^"\\\n]|\\.)*)"', text)


def conversions(s):
    """The printf conversions of s in order (as vk_menu_i18n.cpp conversion() reads them; not ' ': "80% suits" is a sign)"""
    return re.findall(r'%[-+#0]*\d*(?:\.\d+)?[lhz]*[sducxgf%]', s)


def tables():
    src = (VK / "menu_i18n.h").read_text(encoding="utf-8")
    out = {}
    for name, body in re.findall(r'inline constexpr Entry (k\w+)\[\] = \{\n(.*?)\n\};', src, re.S):
        pairs = re.findall(r'^    \{"((?:[^"\\]|\\.)*)", "((?:[^"\\]|\\.)*)"\},$', body, re.M)
        out[name] = pairs
    langs = re.findall(r'^    \{"([\w-]+)", "((?:[^"\\]|\\.)*)", (\w+), (\d+)\},$', src, re.M)
    return out, langs


class MenuI18nTests(unittest.TestCase):
    def setUp(self):
        self.tables, self.langs = tables()
        menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
        self.menu = set(c_strings(menu))

    def test_languages(self):
        self.assertEqual(self.langs[0][:3], ("en", "English", "nullptr"))
        codes = [code for code, _, _, _ in self.langs]
        self.assertEqual(len(codes), len(set(codes)), "a language listed twice")
        for code, _, table, count in self.langs[1:]:
            self.assertIn(table, self.tables, code)
            self.assertEqual(len(self.tables[table]), int(count), "%s: its count is not its table's" % code)

    def test_texts_are_the_menus(self):
        for table, pairs in self.tables.items():
            for en, _ in pairs:
                self.assertTrue(en in self.menu, "%s: %r is no text of vk_menu.cpp (renamed? then translate it again)" % (table, en))

    def test_current_hints_are_translated(self):
        # Whole-string lookup needs the complete hint. Dropping a stale entry and lowering its count is not a fix.
        hints = {
            "controls": (
                "Gamepad: the D-pad moves, A binds, B goes back. Ocarina note keys are only notes while "
                "the ocarina waits for one; away from it they do their other jobs."
            ),
            "automatic button prompts": (
                "Those of the first controller, from its name (SDL's). With none, the keyboard's (the Switch's with XInput "
                "alone)."
            ),
        }
        for name, hint in hints.items():
            self.assertTrue(hint in self.menu, "%s: expected complete hint is no text of vk_menu.cpp" % name)
        for table, pairs in self.tables.items():
            keys = {en for en, _ in pairs}
            for name, hint in hints.items():
                self.assertTrue(hint in keys, "%s: missing current %s hint" % (table, name))

    def test_speaker_layout_texts_are_translated(self):
        texts = ("Speaker layout",
                 "5.1 when the selected/default output has 5.1 or more speakers at startup, else stereo.")
        for text in texts:
            self.assertIn(text, self.menu)
        for table, pairs in self.tables.items():
            translated = dict(pairs)
            for text in texts:
                with self.subTest(table=table, text=text):
                    self.assertIn(text, translated)
                    self.assertNotEqual(translated[text], text)

    def test_output_device_texts_are_translated(self):
        texts = (
            "Output device", "Where the game plays sound. Changes apply without restarting the game.",
            "Where the game plays sound. A change briefly restarts only the audio stream.",
            "HOS_AUDIO_DEVICE overrides this run. The saved device choice is kept.",
            "No playback output could be opened. The game keeps trying.",
            "Default is used temporarily. The selected output is remembered and retried when available.",
            "This playback device. Speaker layout changes still require a game restart.",
            "Follow the Windows default playback device.", "Overridden by HOS_AUDIO_DEVICE",
            "Follow the system default playback device.",
            "Selected output", "Default", " (not connected)",
        )
        self.assertEqual(len(self.tables), 13)
        for text in texts:
            self.assertIn(text, self.menu)
        for table, pairs in self.tables.items():
            translated = dict(pairs)
            for text in texts:
                with self.subTest(table=table, text=text):
                    self.assertIn(text, translated)
                    self.assertNotEqual(translated[text], text)
        source = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
        self.assertIn('std::string(i18n::tr("Selected output"))', source)
        self.assertIn('+ i18n::tr(" (not connected)")', source)

    def test_microphone_test_texts_are_translated(self):
        explanation = (
            r"Shows microphone signal strength, not note recognition.\n\n"
            r"- First percentage: incoming peak before gain.\n"
            r"- Second percentage: peak after Microphone gain, also shown by the bar.\n\n"
            "At 100% gain they match. Increasing gain also raises noise and can clip the signal."
        )
        gain_help = (
            "Adjust capture for Hookshot only; system volume is unchanged. Use the microphone test to see live levels "
            "while adjusting gain. Changes apply to new samples."
        )
        test_help = (
            "Start or stop microphone capture. No playback or audio files. You can adjust Microphone gain while testing. "
            "Leaving Audio, closing the menu or selecting Off stops the test; the game can still use the mic."
        )
        texts = (
            "Microphone gain", "Test microphone", gain_help, test_help, explanation,
            "Testing: %d%% -> %d%%", "Test stopped", "Microphone unavailable", "Waiting for samples", "Clipping",
            "Default fallback", " (Default fallback)", "Microphone Off", "Stop test", "Start test", "Unavailable",
        )
        self.assertEqual(len(self.tables), 13)
        for text in texts:
            self.assertIn(text, self.menu)
        for table, pairs in self.tables.items():
            translated = dict(pairs)
            for text in texts:
                with self.subTest(table=table, text=text):
                    self.assertIn(text, translated)
                    self.assertNotEqual(translated[text], text)
            with self.subTest(table=table):
                # Keep the overview, separate percentage bullets and gain/clipping note in every language.
                self.assertEqual(translated[explanation].count(r"\n\n"), 2)
                self.assertEqual(translated[explanation].count(r"\n- "), 2)
                self.assertEqual(translated[explanation].count(r"\n"), explanation.count(r"\n"))
                self.assertEqual(conversions(translated["Testing: %d%% -> %d%%"]), ["%d", "%%", "%d", "%%"])
                self.assertIn(translated["Microphone gain"], translated[test_help])

    def test_custom_output_texts_are_translated(self):
        texts = (
            "Custom output size",
            "An Output resolution of your own, typed as width x height: your monitor's size, such as 3440x1440, 2560x1080 or "
            "2560x1600. Each side is rounded down to a multiple of 8; a size the Output resolution offers is chosen there. Empty: "
            "none. Docked only. Applies after a restart.",
            "Type the width, an x, then the height: 3440x1440.",
            "Not a size the game can draw: at least 640x360, at most 5120x2880's pixels, from 5:4 to 48:9 in shape.",
            "None", "Edit", "Paste", "Done", "Cancel", "Caret", "Character", "Add", "Remove",
        )
        self.assertEqual(len(self.tables), 13)
        for text in texts:
            self.assertIn(text, self.menu)
        for table, pairs in self.tables.items():
            translated = dict(pairs)
            for text in texts:
                with self.subTest(table=table, text=text):
                    self.assertIn(text, translated)
                    self.assertNotEqual(translated[text], text)

    def test_custom_output_hint_uses_local_row_name(self):
        for table, pairs in self.tables.items():
            translated = dict(pairs)
            with self.subTest(table=table):
                hint = translated["Your own size, from Custom output size below."]
                self.assertNotIn("Custom output size", hint)
                self.assertIn(translated["Custom output size"], hint)

    def test_plural_forms(self):
        # (i18n::plural: Russian and Polish ask for a third form, " settings (many)", for 5 and up; the menu shows it
        # nowhere else, so only their tables have it)
        cpp = (VK / "vk_menu_i18n.cpp").read_text(encoding="utf-8")
        for table, code in (("kru", "ru"), ("kpl", "pl")):
            self.assertIn('code == "%s"' % code, cpp)
            self.assertIn(" settings (many)", dict(self.tables[table]), table)
            self.assertIn(" settings", dict(self.tables[table]), table)

    def test_conversions_and_spaces(self):
        for table, pairs in self.tables.items():
            keys = [en for en, _ in pairs]
            self.assertEqual(len(keys), len(set(keys)), "%s: a text twice" % table)
            self.assertEqual(keys, sorted(keys), "%s: not sorted (menu_i18n.h is written sorted)" % table)
            for en, text in pairs:
                self.assertTrue(text, "%s: %r has an empty translation" % (table, en))
                self.assertEqual(conversions(en), conversions(text), "%s: %r and %r" % (table, en, text))
                for side in (lambda s: s[:len(s) - len(s.lstrip(" "))], lambda s: s[len(s.rstrip(" ")):]):
                    self.assertEqual(side(en), side(text), "%s: the spaces around %r" % (table, en))


if __name__ == "__main__":
    unittest.main()
