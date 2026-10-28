"""复习排程：简化版 SM-2，天数用整数日序号存储，便于 seekdb 元数据过滤。"""

from __future__ import annotations

GRADES = ("again", "hard", "good")
EASE_FLOOR = 130
EASE_CEIL = 320


def new_state(day: int) -> dict:
    return {
        "state": "new",
        "due_day": day,
        "interval_days": 0,
        "ease": 250,
        "reps": 0,
        "lapses": 0,
    }


def grade(state: dict, result: str, today: int) -> dict:
    if result not in GRADES:
        raise ValueError(f"result 必须是 {GRADES} 之一，收到 {result!r}")

    ease = int(state.get("ease", 250))
    interval = int(state.get("interval_days", 0))
    reps = int(state.get("reps", 0))
    lapses = int(state.get("lapses", 0))

    if result == "again":
        interval = 1
        ease = max(EASE_FLOOR, ease - 20)
        lapses += 1
        next_state = "learning"
    elif result == "hard":
        interval = max(1, round(interval * 1.2)) if interval else 1
        ease = max(EASE_FLOOR, ease - 5)
        next_state = "review"
    else:
        if reps == 0:
            interval = 1
        elif interval <= 1:
            interval = 3
        else:
            interval = max(2, round(interval * ease / 100))
        ease = min(EASE_CEIL, ease + 5)
        next_state = "review"

    return {
        "state": next_state,
        "due_day": today + interval,
        "interval_days": interval,
        "ease": ease,
        "reps": reps + 1,
        "lapses": lapses,
    }
