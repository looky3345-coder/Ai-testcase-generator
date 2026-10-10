import json
import unittest

from testgen.case_parser import parse_test_cases

VALID_CASE = {
    "id": "TC-1",
    "technique": "boundary_value_analysis",
    "description": "최대 인원 경계",
    "target_lines": "45-48",
    "preconditions": "",
    "input": "count=101",
    "expected": "422",
    "priority": "high",
}


class ParseTestCasesTest(unittest.TestCase):
    def test_object_with_test_cases(self):
        result = parse_test_cases(json.dumps({"test_cases": [VALID_CASE]}))
        self.assertEqual(result.test_cases, [VALID_CASE])
        self.assertEqual(result.errors, [])

    def test_legacy_top_level_array(self):
        result = parse_test_cases(json.dumps([VALID_CASE]))
        self.assertEqual(len(result.test_cases), 1)

    def test_code_fence_and_surrounding_text(self):
        raw = "다음은 결과입니다.\n```json\n" + json.dumps({"test_cases": [VALID_CASE]}) + "\n```\n끝."
        self.assertEqual(len(parse_test_cases(raw).test_cases), 1)

    def test_text_before_json_without_fence(self):
        raw = "설명 문장 {잡음} " + json.dumps({"test_cases": [VALID_CASE]})
        self.assertEqual(len(parse_test_cases(raw).test_cases), 1)

    def test_invalid_cases_dropped_with_reasons(self):
        bad = dict(VALID_CASE, technique="decision_table")
        missing = {k: v for k, v in VALID_CASE.items() if k != "expected"}
        result = parse_test_cases(json.dumps({"test_cases": [VALID_CASE, bad, missing]}))
        self.assertEqual(result.test_cases, [VALID_CASE])
        self.assertEqual(len(result.errors), 2)
        self.assertIn("technique", result.errors[0])
        self.assertIn("expected", result.errors[1])

    def test_no_json(self):
        result = parse_test_cases("JSON이 없는 응답")
        self.assertEqual(result.test_cases, [])
        self.assertTrue(result.errors)

    def test_wrong_top_level(self):
        result = parse_test_cases('{"cases": []}')
        self.assertEqual(result.test_cases, [])
        self.assertIn("test_cases", result.errors[0])


if __name__ == "__main__":
    unittest.main()
