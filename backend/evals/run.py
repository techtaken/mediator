"""Run the scenario evals against the real Gemini API.

    cd backend
    python -m evals.run                       # all scenarios
    python -m evals.run --scenario loan-50k   # one (repeatable)
    python -m evals.run --list
    python -m evals.run --out evals/reports

Needs GEMINI_API_KEY (environment or backend/.env). Without one it prints a
note and exits 0, so it is safe to call from CI. It never touches Supabase.
Writes eval-<time>.json and eval-<time>.md to the output folder and exits 1
if any scenario failed.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUT = BACKEND_DIR / "evals" / "reports"


def _env_file_has(name: str) -> bool:
    env = BACKEND_DIR / ".env"
    if not env.exists():
        return False
    for line in env.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name and value.strip():
            return True
    return False


def gemini_key_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY")) or _env_file_has("GEMINI_API_KEY")


def _placeholder_database_settings() -> None:
    # Settings require Supabase values, but evals never use the database.
    for name, value in (("SUPABASE_URL", "https://evals-unused.invalid"), ("SUPABASE_SECRET_KEY", "evals-unused")):
        if name not in os.environ and not _env_file_has(name):
            os.environ[name] = value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Mediator scenario and red-team evals (live Gemini).")
    parser.add_argument("--scenario", action="append", default=[], help="scenario id to run (repeatable)")
    parser.add_argument("--list", action="store_true", help="list scenario ids and exit")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for the JSON and Markdown report")
    args = parser.parse_args(argv)

    from evals.harness import load_scenarios

    scenarios = load_scenarios()
    if args.list:
        for scenario in scenarios:
            print(f"{scenario['id']:28} {scenario.get('language', ''):9} {', '.join(scenario.get('tags') or [])}")
        return 0
    if args.scenario:
        wanted = set(args.scenario)
        unknown = wanted - {scenario["id"] for scenario in scenarios}
        if unknown:
            print(f"Unknown scenario(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        scenarios = [scenario for scenario in scenarios if scenario["id"] in wanted]

    if not gemini_key_available():
        print("GEMINI_API_KEY is not set (environment or backend/.env); skipping live evals.")
        return 0

    _placeholder_database_settings()
    from app.agents.llm import call_agent
    from app.agents.telemetry import collect_calls
    from app.config import get_settings
    from evals.harness import run_scenario
    from evals.report import build, write

    started = datetime.now(timezone.utc).isoformat()
    results, prompt_tokens, output_tokens = [], 0, 0
    for scenario in scenarios:
        began = time.monotonic()
        with collect_calls() as records:
            result = run_scenario(scenario, call_agent)
        prompt_tokens += sum(record.prompt_tokens or 0 for record in records)
        output_tokens += sum(record.output_tokens or 0 for record in records)
        status = "pass" if result.passed else "FAIL"
        print(f"{status:4} {scenario['id']:28} {result.calls:3} calls  {time.monotonic() - began:5.1f}s  "
              + "; ".join(result.failures))
        results.append(result)

    report = build(
        results,
        {
            "started_at": started,
            "mode": "live",
            "model": get_settings().gemini_model,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
        },
    )
    json_path, md_path = write(report, args.out)
    summary = report["summary"]
    print(f"\n{summary['passed']}/{summary['scenarios']} passed · leaks {summary['leaks']} · "
          f"safety recall {summary['safety_recall']} · report {md_path}")
    print(f"JSON: {json_path}")
    return 0 if summary["passed"] == summary["scenarios"] else 1


if __name__ == "__main__":
    sys.exit(main())
