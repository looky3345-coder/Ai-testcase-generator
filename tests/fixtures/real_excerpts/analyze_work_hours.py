# 실제 대상 프로젝트(Checkine-Automation-Project/backend/app/services/ai_service.py)의
# analyze_work_hours를 사용자가 공유한 프롬프트에서 그대로 옮긴 발췌. 분기 체크리스트 추출 검증용 (실행하지 않음).
from sqlalchemy.orm import Session
from models.attendance import Attendance
from utils.kst import get_kst_now
from services.slack_service import get_today_deep_work_metrics


def generate_with_retry(prompt, max_retries=5, system_prompt=None, max_tokens=None):
    pass


def analyze_work_hours(db: Session, user_id: int, current_work_seconds: int):
    past_records = db.query(Attendance).filter(Attendance.user_id == user_id, Attendance.status == "DONE").order_by(Attendance.id.desc()).limit(5).all()
    if len(past_records) < 3: return "오늘 하루도 정말 고생 많으셨습니다! 조심히 들어가세요. 🌙"

    total_seconds = sum((record.work_seconds or 0) for record in past_records)
    avg_seconds = total_seconds / len(past_records)
    diff_minutes = (current_work_seconds - avg_seconds) / 60
    day_of_week = get_kst_now().strftime("%A")
    hours = current_work_seconds / 3600

    slack_metrics = get_today_deep_work_metrics() or {"dnd_active": False, "status_text": ""}
    dnd_status = "Used Deepwork" if slack_metrics.get("dnd_active") else "Not Used"

    요일_map = {"Monday": "월요일", "Tuesday": "화요일", "Wednesday": "수요일",
               "Thursday": "목요일", "Friday": "금요일", "Saturday": "토요일", "Sunday": "일요일"}
    day_of_week = 요일_map.get(day_of_week, day_of_week)
    work_summary = f"오늘 {hours:.1f}시간 근무"
    if hours <= 5:
        work_summary += " (반차 또는 단축 근무 가능성)"
    prompt = f"""[상황]
- 요일: {day_of_week}
- {work_summary}
- 딥워크 집중 여부: {'집중함' if dnd_status == 'Used Deepwork' else '집중 안 함'}
- 슬랙 상태창: {slack_metrics.get('status_text') or '없음'}
"""
    try:
        return generate_with_retry(prompt, max_tokens=80)
    except Exception as e:
        print(f"GEMINI ERROR: {str(e)}")
        return "AI 매니저가 잠시 디버깅 중이에요! 🛠️ 곧 위트 있는 분석을 가져올게요."
