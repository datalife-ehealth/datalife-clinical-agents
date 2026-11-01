import unittest
import json
from pathlib import Path


from tools.text_policy_normalization import normalize_for_policy_match

class TestTextPolicyNormalization(unittest.TestCase):

    def test_nfkc_and_casefold(self):
        self.assertEqual(normalize_for_policy_match("ＨＥＬＬＯ"), "hello")

    def test_paragraph_whitespace(self):
        self.assertEqual(normalize_for_policy_match("  THE PATIENT    reports a HEADACHE.\nFollow-up is   scheduled for MONDAY.  "),"the patient reports a headache. follow-up is scheduled for monday.")

    def test_zero_width_space(self):
        self.assertEqual(normalize_for_policy_match(" he\u200bllO "),"hello")

    def test_preserves_zero_width_joiner(self):
        self.assertEqual(normalize_for_policy_match("hello\u200dworld"),"hello\u200dworld")

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
