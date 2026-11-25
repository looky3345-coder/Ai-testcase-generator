import unittest
from testgen.prompt_builder import build_prompt
from testgen.models import TestTarget

class PatchHintTest(unittest.TestCase):
    def make_target(self, dependencies):
        return TestTarget(
            file="app/services/ai_service.py",
            qualname="analyze_work_hours",
            start_line=1,
            signature=None,
            source="",
            truncated=False,
            module_name="services.ai_service",
            dependencies=dependencies
        )
        
    def test_attendance(self):
        target = self.make_target(["Session: from sqlalchemy.orm import Session (타입 표기에만 사용 — mock 불필요)",
        "Attendance: from models.attendance import Attendance",
        "get_kst_now: from utils.kst import get_kst_now",])
        prompt_str = build_prompt(target)
        self.assertIn('patch("services.ai_service.Attendance")', prompt_str)
    
    def test_no_hint_when_all_unneeded(self):
        target = self.make_target(["module_name: mock 불필요"])
        prompt_str = build_prompt(target)
        self.assertNotIn('예: patch(', prompt_str)
    
    def test_first_callable_kept(self):
        target = self.make_target(["get_kst_now: from utils.kst import get_kst_now"])
        prompt_str = build_prompt(target)
        self.assertIn('patch("services.ai_service.get_kst_now")', prompt_str)