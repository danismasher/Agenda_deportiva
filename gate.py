#!/usr/bin/env python3
"""Decide si merece la pena ejecutar la actualizacion completa en esta pasada."""
import json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
now = datetime.now(timezone.utc)
today = now.date().isoformat()


def decide():
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return True, "ejecucion manual"
    if now.hour in (5, 17) and now.minute < 20:
        return True, "pasada diaria programada"
    try:
        events = json.loads((ROOT / "events.json").read_text("utf-8")).get("events", [])
    except Exception:
        return True, "no hay events.json"
    if not events:
        return True, "events.json vacio"
    for e in events:
        if e.get("res"):
            continue
        if e.get("start"):
            dt = datetime.strptime(e["start"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if now - timedelta(hours=8) <= dt <= now + timedelta(minutes=15):
                return True, f"evento en curso o recien terminado: {e['s']} {e['title'][:40]}"
        elif e.get("date") == today and now.minute < 10:
            return True, f"evento de hoy sin hora ni resultado: {e['s']}"
    return False, "nada en curso"


run, why = decide()
print(f"run={'true' if run else 'false'} ({why})")
out = os.environ.get("GITHUB_OUTPUT")
if out:
    with open(out, "a") as f:
        f.write(f"run={'true' if run else 'false'}\n")
