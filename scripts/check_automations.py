"""
Check the status of DailyMe OpenHands automations.

Usage:
    uv run python scripts/check_automations.py
    uv run python scripts/check_automations.py --runs 10   # show last N runs per automation
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# Auto-load .env from project root (two levels up from this script)
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

AUTOMATIONS = {
    "Newsletter Pipeline": "5fbefeb3-9f35-459e-8b5c-54959be03cb0",
    "Social Pipeline": "2129c579-8fb7-4562-9024-6b16af843b6c",
}

STATUS_ICONS = {
    "COMPLETED": "✅",
    "FAILED": "❌",
    "RUNNING": "⏳",
    "PENDING": "🕐",
}


def _api(path: str, api_key: str) -> dict | list:
    resp = requests.get(
        f"https://app.all-hands.dev/api/automation/v1{path}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _fmt_time(ts: str | None) -> str:
    if not ts:
        return "never"
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    delta = now - dt
    minutes = int(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5, help="Number of recent runs to show (default: 5)")
    args = parser.parse_args()

    api_key = os.getenv("OH_API_KEY") or os.getenv("OPENHANDS_API_KEY")
    if not api_key:
        print("ERROR: OH_API_KEY or OPENHANDS_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print("  DailyMe Automation Status")
    print(f"  Checked: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    all_ok = True

    for name, automation_id in AUTOMATIONS.items():
        try:
            info = _api(f"/{automation_id}", api_key)
        except requests.HTTPError as e:
            print(f"⚠️  {name}: could not fetch ({e})\n")
            all_ok = False
            continue

        enabled = info.get("enabled", False)
        last_triggered = _fmt_time(info.get("last_triggered_at"))
        schedule = info.get("trigger", {}).get("schedule", "?")

        status_str = "🟢 enabled" if enabled else "🔴 disabled"
        print(f"📋 {name}")
        print(f"   Status:       {status_str}")
        print(f"   Schedule:     {schedule} (every 2h UTC)")
        print(f"   Last trigger: {last_triggered}")
        print(f"   ID:           {automation_id}")

        try:
            runs_data = _api(f"/{automation_id}/runs?limit={args.runs}", api_key)
            runs = runs_data if isinstance(runs_data, list) else runs_data.get("items", [])
        except Exception as e:
            print(f"   ⚠️  Could not fetch runs: {e}")
            runs = []

        if runs:
            print(f"\n   Last {len(runs)} run(s):")
            for run in runs:
                icon = STATUS_ICONS.get(run.get("status", ""), "❓")
                ts = _fmt_time(run.get("created_at") or run.get("started_at"))
                status = run.get("status", "unknown")
                run_id = run.get("id", "?")[:8]
                error = run.get("error_detail", "")
                line = f"   {icon} {status:<12} {ts:<12} (id: {run_id})"
                if error and status == "FAILED":
                    line += f"\n        └─ {error[:80]}"
                print(line)
                if status == "FAILED":
                    all_ok = False
        else:
            print("   No runs recorded yet.")

        print()

    print(f"{'='*60}")
    if all_ok:
        print("✅ All automations healthy")
    else:
        print("⚠️  One or more automations need attention")
    print()


if __name__ == "__main__":
    main()
