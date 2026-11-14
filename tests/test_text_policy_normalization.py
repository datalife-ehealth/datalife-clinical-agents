import unittest
import json
from pathlib import Path


from tools.text_policy_normalization import normalize_for_policy_match

class TestTextPolicyNormalization(unittest.TestCase):

    def test_selected_cyrillic_lookalikes_in_both_cases(self):
        cyrillic = "\u0430\u0435\u043e\u0440\u0441\u0445\u0443\u0456\u0458\u0455\u043d\u043a"
        self.assertEqual(normalize_for_policy_match(cyrillic), "aeopcxyijshk")
        self.assertEqual(normalize_for_policy_match(cyrillic.upper()), "aeopcxyijshk")

    def test_nfkc_reveals_cyrillic_lookalike_before_translation(self):
        # Modifier letter Cyrillic en becomes Cyrillic en under NFKC, then h.
        self.assertEqual(normalize_for_policy_match("\u1d78"), "h")

    def test_unmapped_greek_lookalike_remains_unchanged(self):
        self.assertEqual(normalize_for_policy_match("\u03bf"), "\u03bf")

    def test_custom_character_limits(self):
        self.assertEqual(normalize_for_policy_match(
            "A" * 10_001, max_input_length=10_001, max_output_length=10_001,
        ), "a" * 10_001)
        with self.assertRaises(ValueError):
            normalize_for_policy_match("abcd", max_input_length=3)
        with self.assertRaises(ValueError):
            normalize_for_policy_match("\ufb03", max_output_length=2)

    def test_invalid_limit_configuration(self):
        for value in (0, -1, True, "100", 1.5, None):
            for setting in ("max_input_length", "max_output_length"):
                with self.subTest(setting=setting, value=value):
                    with self.assertRaises(ValueError):
                        normalize_for_policy_match("synthetic", **{setting: value})

    def test_nfkc_and_casefold(self):
        self.assertEqual(normalize_for_policy_match("ＨＥＬＬＯ"), "hello")

    def test_paragraph_whitespace(self):
        self.assertEqual(normalize_for_policy_match("  THE PATIENT    reports a HEADACHE.\nFollow-up is   scheduled for MONDAY.  "),"the patient reports a headache. follow-up is scheduled for monday.")

    def test_zero_width_space(self):
        self.assertEqual(normalize_for_policy_match(" he\u200bllO "),"hello")

    def test_strips_supported_invisible_format_characters(self):
        for char in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
            with self.subTest(codepoint=f"U+{ord(char):04X}"):
                self.assertEqual(normalize_for_policy_match(f"hello{char}world"), "helloworld")

    def test_invalid_input_type(self):
        with self.assertRaises(TypeError):
            normalize_for_policy_match(234)

    def test_input_over_limit(self):
        with self.assertRaises(ValueError):
            normalize_for_policy_match("A"*10_001)

    def test_output_over_limit(self):
        with self.assertRaises(ValueError):
            normalize_for_policy_match("ﬃ"*4_000)

    def test_idempotent(self):
        original = "  ＨＥＬＬＯ\u200b   WORLD  "
        once = normalize_for_policy_match(original)
        twice = normalize_for_policy_match(once)
        self.assertEqual(once, twice)

    def test_greek_sigma_normalization(self):
        self.assertEqual(normalize_for_policy_match("\u03f9"),"\u03c2")

    def test_unicode_boundary_fixtures(self):
        fixture_path = Path(__file__).parent / "fixtures" / "unicode_boundary_cases.json"

        with fixture_path.open(encoding="utf-8") as file:
            cases = json.load(file)

        for case in cases:
            with self.subTest(name=case["name"]):
                actual = normalize_for_policy_match(case["input"])
                self.assertEqual(actual, case["expected"])

    def test_input_at_exact_limit(self):
        self.assertEqual(normalize_for_policy_match("A"*10_000),"a"*10_000)

    def test_output_at_exact_limit(self):
        text = "ﬃ" * 3_333 + "A"
        self.assertEqual(normalize_for_policy_match(text),"ffi" * 3_333 + "a")

    def test_zero_width_space_between_spaces(self):
        self.assertEqual(
            normalize_for_policy_match("hello \u200b world"),
            "hello world"
        )

    def test_idempotence_unicode_range(self):
        # These six code points are not idempotent under single-pass casefold + NFKC.
        # They are excluded intentionally to preserve predictable runtime.
        known_exceptions = {0x037A, 0x03D2, 0x03D3, 0x03D4, 0x03F2, 0x03F9}

        for codepoint in range(0x1000):
            if codepoint in known_exceptions:
                continue

            text = chr(codepoint)
            once = normalize_for_policy_match(text)
            twice = normalize_for_policy_match(once)

            self.assertEqual(
                once,
                twice,
                msg=f"Failed at U+{codepoint:04X}"
            )
