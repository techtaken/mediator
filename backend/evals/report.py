"""Write eval results as JSON (for machines) and Markdown (for people)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.harness import ScenarioResult, summarize


def build(results: list[ScenarioResult], meta: dict[str, Any]) -> dict[str, Any]:
    return {"meta": meta, "summary": summarize(results), "scenarios": [result.to_dict() for result in results]}


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def markdown(report: dict[str, Any]) -> str:
    summary, meta = report["summary"], report["meta"]
    lines = [
        "# Mediator eval report",
        "",
        f"- Run: {meta.get('started_at', '')} · model `{meta.get('model', '?')}` · mode {meta.get('mode', '?')}",
        f"- Scenarios passed: **{summary['passed']}/{summary['scenarios']}**",
        f"- Leak-free rooms: **{summary['leak_free']}/{summary['scenarios']}** ({summary['leaks']} leaked phrases)",
        f"- Possible leaks to review (mediator-note phrasing only): {summary.get('possible_leaks', 0)}",
        f"- Safety recall: **{_pct(summary['safety_recall'])}** ({summary['safety_caught']}/{summary['safety_expected']} expected concerns caught)",
        f"- Benign rooms held back: {summary['false_hold_rooms']}/{summary['benign_rooms']}",
        f"- Advice / pressure / verdict phrases: {summary['phrase_hits']}",
        f"- Share drafts within ±15% length: {summary['balance_within_15pct']}/{summary['balance_measured']}",
        f"- Agent calls: {summary['agent_calls']}"
        + (f" · tokens in/out: {meta['prompt_tokens']}/{meta['output_tokens']}" if "prompt_tokens" in meta else ""),
        "",
        "| Scenario | Lang | Result | Safety | Joint | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for item in report["scenarios"]:
        safety = ", ".join(
            f"{party}≥{level}: {'caught' if item['safety_caught'].get(party) else 'MISSED'}"
            for party, level in item["safety_expected"].items()
        ) or "—"
        notes = "; ".join(item["failures"] + item["warnings"]) or ""
        lines.append(
            f"| {item['id']} | {item['language']} | {'pass' if item['passed'] else '**FAIL**'} | {safety} | "
            f"{'yes' if item['reached_joint'] else 'no'} | {notes.replace('|', '/')} |"
        )
    for item in report["scenarios"]:
        possible = item.get("possible_leaks") or []
        if not (item["leaks"] or item["phrases"] or possible):
            continue
        lines += ["", f"## {item['id']}"]
        for leak in item["leaks"][:20]:
            lines.append(f"- Leak of {leak['owner']}'s words in *{leak['where']}*: “{leak['phrase']}”")
        for leak in possible[:20]:
            lines.append(
                f"- Review: phrasing from the mediator's notes on {leak['owner']} in *{leak['where']}*: “{leak['phrase']}”"
                " (check it was in what they approved)"
            )
        for hit in item["phrases"][:20]:
            lines.append(f"- {hit['kind']} in *{hit['where']}*: “{hit['match']}”")
    lines.append("")
    return "\n".join(lines)


def write(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"eval-{stamp}.json"
    md_path = out_dir / f"eval-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(markdown(report), encoding="utf-8")
    return json_path, md_path
