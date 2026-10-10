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

    def test_think_block_stripped(self):
        # 사고 과정 안에 중괄호가 섞여 있어도 답 부분의 JSON을 읽어야 한다
        raw = "<think>입력은 {score} 같은 형태... 경계는 {3}</think>\n" + json.dumps({"test_cases": [VALID_CASE]})
        self.assertEqual(len(parse_test_cases(raw).test_cases), 1)

    def test_unclosed_think_reports_truncation(self):
        result = parse_test_cases("<think>아직 생각 중인데 출력이 끊김 {")
        self.assertEqual(result.test_cases, [])
        self.assertIn("잘렸을", result.errors[0])

    def test_empty_and_think_only(self):
        self.assertIn("비어 있습니다", parse_test_cases("").errors[0])
        self.assertIn("<think>만", parse_test_cases("<think>생각만</think>").errors[0])

    def test_truncated_response_salvages_complete_cases(self):
        # 실제 사례 재현: finish_reason=length로 셋째 케이스 중간에서 잘림
        second = dict(VALID_CASE, id="TC-2", preconditions="get_today_deep_work_metrics는 {'dnd_active': True} 반환")
        whole = json.dumps({"test_cases": [VALID_CASE, second, dict(VALID_CASE, id="TC-3")]}, ensure_ascii=False, indent=2)
        truncated = whole[: whole.index('"TC-3"') + 3]
        result = parse_test_cases(truncated)
        self.assertEqual([c["id"] for c in result.test_cases], ["TC-1", "TC-2"])
        self.assertIn("완성된 케이스 2개만 회수", result.errors[0])

    def test_truncated_before_any_complete_case(self):
        result = parse_test_cases('{"test_cases": [{"id": "TC-1", "techni')
        self.assertEqual(result.test_cases, [])
        self.assertTrue(result.errors)

    def test_duplicate_cases_flagged_not_dropped(self):
        # 실제 사례: TC-6/TC-8이 같은 입력·사전조건
        dup = dict(VALID_CASE, id="TC-2", description="다른 설명", target_lines="99")
        other = dict(VALID_CASE, id="TC-3", input="count=99")
        result = parse_test_cases(json.dumps({"test_cases": [VALID_CASE, dup, other]}))
        self.assertEqual(len(result.test_cases), 3)
        self.assertEqual(result.errors, ["중복 의심: TC-2의 입력·사전조건이 TC-1와 같음"])

    def test_common_preconditions(self):
        raw = json.dumps({"common_preconditions": "patch('m.f')는 'X' 반환", "test_cases": [VALID_CASE]})
        result = parse_test_cases(raw)
        self.assertEqual(result.common_preconditions, "patch('m.f')는 'X' 반환")
        # 이전 형식(공통 사전조건 없음)도 허용
        self.assertEqual(parse_test_cases(json.dumps({"test_cases": [VALID_CASE]})).common_preconditions, "")

    def test_common_preconditions_salvaged_from_truncated(self):
        whole = json.dumps(
            {"common_preconditions": "공통 \"mock\"", "test_cases": [VALID_CASE, dict(VALID_CASE, id="TC-2")]},
            ensure_ascii=False,
        )
        truncated = whole[: whole.index('"TC-2"') + 3]
        result = parse_test_cases(truncated)
        self.assertEqual(result.common_preconditions, '공통 "mock"')
        self.assertEqual(len(result.test_cases), 1)

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
