from __future__ import annotations

import json
import logging
import os
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.collectors.company_official_collector import collect_company_official_sources
from app.collectors.industry_collector import collect_fred_semiconductor_indicators
from app.collectors.macro_collector import collect_customs_trade, collect_kosis_stats
from app.collectors.market_collector import (
    collect_ecos_exchange_rate,
    collect_global_stock_prices,
    collect_krx_daily,
    collect_krx_investor_flows,
)
from app.collectors.news_collector import collect_rss_all_sources, collect_tech_blogs
from app.collectors.paper_collector import (
    collect_openalex_company_priority_papers,
    monitor_arxiv_company_papers,
    monitor_arxiv_new_papers,
)
from app.db.schema import ensure_postgres_schema
from app.events.builder import build_event_dataset
from app.experience import build_forecast_experience_memory
from app.experience.backtest_chunks import run_chunked_semiconductor_backtests
from app.rag.evaluator import evaluate_rag
from app.rag.indexer import index_all_chunks_safe
from app.run_data_coverage_report import fetch_summary
from app.run_experience_report import fetch_report

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
LATEST_MD = REPORT_DIR / "overnight_semiconductor_latest.md"
LATEST_JSON = REPORT_DIR / "overnight_semiconductor_latest.json"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _run_step(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    try:
        result = fn()
        return {
            "name": name,
            "ok": True,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "result": result,
        }
    except Exception as e:
        logging.getLogger("overnight").exception("Overnight step failed | %s", name)
        return {
            "name": name,
            "ok": False,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "traceback": traceback.format_exc(limit=4),
        }


def _render_markdown(payload: dict[str, Any]) -> str:
    counts = (payload.get("coverage") or {}).get("counts", {})
    experience = payload.get("experience_report") or {}
    backtest = payload.get("backtest_chunks") or {}
    rag = payload.get("rag_eval") or {}
    steps = payload.get("steps") or []

    lines = [
        "# Overnight Semiconductor Agent Report",
        "",
        f"- generated_at: `{payload.get('generated_at', '')}`",
        f"- overnight_hours: `{payload.get('overnight_hours', '')}`",
        "",
        "## What Ran",
        "",
    ]
    for step in steps:
        status = "ok" if step.get("ok") else "failed"
        lines.append(f"- `{step.get('name')}`: `{status}`")

    lines += [
        "",
        "## Data Snapshot",
        "",
        f"- tech_documents: `{counts.get('tech_documents', 0)}`",
        f"- tech_document_chunks: `{counts.get('tech_document_chunks', 0)}`",
        f"- event_candidates: `{counts.get('event_candidates', 0)}`",
        f"- price_forecasts: `{counts.get('price_forecasts', 0)}`",
        f"- price_forecast_evaluations: `{counts.get('price_forecast_evaluations', 0)}`",
        "",
        "## RAG Check",
        "",
        f"- passed: `{rag.get('passed', 0)}/{rag.get('total', 0)}`",
        f"- pass_rate: `{float(rag.get('pass_rate', 0.0)):.1%}`",
        "",
        "## Backtest Progress",
        "",
        f"- completed_tasks: `{backtest.get('completed_tasks', 0)}/{backtest.get('total_tasks', 0)}`",
        f"- pending_tasks: `{backtest.get('pending_tasks', 0)}`",
        f"- ran_cases_this_run: `{backtest.get('ran_cases', 0)}`",
        f"- checkpoint: `{backtest.get('checkpoint_path', '')}`",
        "",
        "## Experience Memory",
        "",
        f"- case_count: `{experience.get('case_count', 0)}`",
    ]
    for label, count in experience.get("success_labels", [])[:3]:
        lines.append(f"- {label}: `{count}`")
    lines.append("")
    lines.append("## Top Error Patterns")
    lines.append("")
    for pattern, count in experience.get("primary_patterns", [])[:5]:
        lines.append(f"- `{pattern}`: `{count}`")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- This report is written by the overnight automation.")
    lines.append("- Long backtests are processed in chunks and resume from checkpoint.")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    overnight_hours = _env_int("OVERNIGHT_HOURS", 8)
    collection_cycles = _env_int("OVERNIGHT_COLLECTION_CYCLES", 3)
    collection_sleep_min = _env_int("OVERNIGHT_COLLECTION_SLEEP_MIN", 90)
    backtest_max_tasks = _env_int("OVERNIGHT_BACKTEST_MAX_TASKS", 4)
    backtest_step_days = _env_int("OVERNIGHT_BACKTEST_STEP_DAYS", 21)
    rag_limit = _env_int("OVERNIGHT_RAG_LIMIT", 6)

    ensure_postgres_schema()

    steps: list[dict[str, Any]] = []
    steps.append(_run_step("krx_daily", collect_krx_daily))
    steps.append(_run_step("krx_investor_flows", collect_krx_investor_flows))
    steps.append(_run_step("global_stock_prices", collect_global_stock_prices))
    steps.append(_run_step("ecos_exchange_rate", collect_ecos_exchange_rate))
    steps.append(_run_step("fred_semiconductor_indicators", collect_fred_semiconductor_indicators))
    steps.append(_run_step("customs_trade", collect_customs_trade))
    steps.append(_run_step("kosis_stats", collect_kosis_stats))

    for cycle_idx in range(max(1, collection_cycles)):
        prefix = f"cycle_{cycle_idx + 1}"
        steps.append(_run_step(f"{prefix}_company_official_sources", collect_company_official_sources))
        steps.append(_run_step(f"{prefix}_rss_all_sources", collect_rss_all_sources))
        steps.append(_run_step(f"{prefix}_tech_blogs", collect_tech_blogs))
        steps.append(_run_step(f"{prefix}_arxiv_new_papers", monitor_arxiv_new_papers))
        steps.append(_run_step(f"{prefix}_arxiv_company_papers", monitor_arxiv_company_papers))
        steps.append(_run_step(f"{prefix}_openalex_company_priority_papers", collect_openalex_company_priority_papers))
        if cycle_idx < max(1, collection_cycles) - 1:
            time.sleep(max(0, collection_sleep_min) * 60)

    steps.append(_run_step("build_event_dataset", build_event_dataset))
    steps.append(_run_step("index_all_chunks", index_all_chunks_safe))

    rag_eval = _run_step("evaluate_rag", lambda: evaluate_rag(limit=rag_limit))
    steps.append(rag_eval)

    backtest_chunks = _run_step(
        "chunked_backtest",
        lambda: run_chunked_semiconductor_backtests(
            company_codes=["005930", "000660", "042700"],
            horizons=[7, 14, 30],
            start_date="2021-06-01",
            end_date="2026-05-20",
            step_days=backtest_step_days,
            window_days=180,
            max_tasks=backtest_max_tasks,
            persist=True,
            checkpoint_path=REPORT_DIR / "overnight_backtest_checkpoint.json",
        ),
    )
    steps.append(backtest_chunks)

    experience_build = _run_step("build_experience_memory", build_forecast_experience_memory)
    steps.append(experience_build)

    coverage = fetch_summary()
    experience_report = fetch_report()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overnight_hours": overnight_hours,
        "steps": steps,
        "coverage": coverage,
        "rag_eval": rag_eval.get("result", {}) if rag_eval.get("ok") else {},
        "backtest_chunks": backtest_chunks.get("result", {}) if backtest_chunks.get("ok") else {},
        "experience_build": experience_build.get("result", {}) if experience_build.get("ok") else {},
        "experience_report": experience_report,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    md_text = _render_markdown(payload)
    (REPORT_DIR / f"overnight_semiconductor_{stamp}.md").write_text(md_text, encoding="utf-8")
    (REPORT_DIR / f"overnight_semiconductor_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    LATEST_MD.write_text(md_text, encoding="utf-8")
    LATEST_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"report_md": str(LATEST_MD), "report_json": str(LATEST_JSON)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
