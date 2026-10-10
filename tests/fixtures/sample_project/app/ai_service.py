import os
from datetime import datetime

from app.clients import Client, get_today_metrics

API_KEY = os.environ.get("API_KEY", "dummy")
client = Client(api_key=API_KEY)


def generate_with_retry(prompt: str, max_tokens: int = 100) -> str:
    return prompt[:max_tokens]


def summarize(records, current_seconds: int):
    if len(records) < 3: return "default"

    avg = sum(records) / len(records)
    hours = current_seconds / 3600

    metrics = get_today_metrics() or {"dnd_active": False}
    names = {"a": 1,
             "b": 2}
    summary = f"{hours:.1f}h"
    if hours <= 5:
        summary += " short"
    prompt = f"""line one
{summary}
avg {avg}
end"""
    try:
        return generate_with_retry(prompt, max_tokens=80)
    except Exception as e:
        print(f"ERROR {e} {datetime.now()} {names} {metrics}")
        return "fallback"
