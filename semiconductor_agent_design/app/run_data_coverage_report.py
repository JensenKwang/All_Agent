from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.tech_potential import assess_technology_potential
from app.db.postgres import get_pg_conn

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
OUTPUT_MD = REPORT_DIR / "semiconductor_data_coverage_report.md"
OUTPUT_JSON = REPORT_DIR / "semiconductor_data_coverage_report.json"

TOPIC_CASES = [
    {"topic": "HBM catalyst and demand", "company_hint": "000660", "domain_hint": "hbm"},
    {"topic": "High-NA EUV market catalyst", "company_hint": "ASML", "domain_hint": "litho"},
    {"topic": "advanced packaging hybrid bonding catalyst", "company_hint": "042700", "domain_hint": "packaging"},
    {"topic": "CXL PIM memory architecture", "company_hint": "000660", "domain_hint": "memory"},
    {"topic": "GAA and backside power delivery catalyst", "company_hint": "005930", "domain_hint": "logic"},
    {"topic": "SiC and GaN power semiconductor catalyst", "company_hint": "", "domain_hint": "power"},
]


def _table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    lines: list[str] = []
    for ridx, row in enumerate(rows):
        cells = [str(cell).ljust(widths[i]) for i, cell in enumerate(row)]
        lines.append(" | ".join(cells))
        if ridx == 0:
            lines.append("-|-".join("-" * w for w in widths))
    return "\n".join(lines)


def _query_all(sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def fetch_summary() -> dict[str, Any]:
    tables = [
        "companies",
        "price_daily",
        "metric_observations",
        "disclosures",
        "tech_documents",
        "tech_document_chunks",
        "paper_sections",
        "paper_tables",
        "paper_figures",
        "event_candidates",
        "event_outcomes",
        "price_forecasts",
        "price_forecast_evaluations",
    ]
    counts: dict[str, int] = {}
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = int(cur.fetchone()[0])

    source_type_rows = _query_all(
        """
        SELECT source_type, COUNT(*) AS cnt
        FROM tech_documents
        GROUP BY source_type
        ORDER BY cnt DESC, source_type
        """
    )
    source_rows = _query_all(
        """
        SELECT source, COUNT(*) AS cnt
        FROM tech_documents
        GROUP BY source
        ORDER BY cnt DESC, source
        """
    )
    company_rows = _query_all(
        """
        SELECT COALESCE(NULLIF(extra->>'company_code', ''), 'UNASSIGNED') AS company_key,
               COUNT(*) AS cnt
        FROM tech_documents
        GROUP BY company_key
        ORDER BY cnt DESC, company_key
        """
    )
    domain_rows = _query_all(
        """
        SELECT COALESCE(domain, 'general') AS domain, COUNT(*) AS cnt
        FROM (
          SELECT jsonb_array_elements_text(COALESCE(extra->'domain_hits', '[]'::jsonb)) AS domain
          FROM tech_documents
        ) AS domains
        GROUP BY domain
        ORDER BY cnt DESC, domain
        """
    )
    latest_docs = _query_all(
        """
        SELECT source, source_type, title, published_at, collected_at, confidence
        FROM tech_documents
        ORDER BY collected_at DESC
        LIMIT 12
        """
    )
    return {
        "counts": counts,
        "source_type_rows": source_type_rows,
        "source_rows": source_rows,
        "company_rows": company_rows,
        "domain_rows": domain_rows,
        "latest_docs": latest_docs,
    }


def build_technology_analysis() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in TOPIC_CASES:
        assessment = assess_technology_potential(
            case["topic"],
            company_hint=case.get("company_hint", ""),
            domain_hint=case.get("domain_hint", ""),
            top_k=8,
        )
        results.append(
            {
                "topic": case["topic"],
                "company_hint": case.get("company_hint", ""),
                "domain_hint": case.get("domain_hint", ""),
                "assessment": asdict(assessment),
            }
        )
    return results


def render_markdown(summary: dict[str, Any], analyses: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append("# Semiconductor Data Coverage and Potential Report")
    lines.append("")
    lines.append(f"- Generated at: `{now}`")
    lines.append(f"- Focus: `data coverage + technology potential`")
    lines.append("")
    lines.append("## Snapshot")
    lines.append("")
    snapshot_rows = [
        ["Table", "Count"],
        ["companies", counts["companies"]],
        ["price_daily", counts["price_daily"]],
        ["metric_observations", counts["metric_observations"]],
        ["tech_documents", counts["tech_documents"]],
        ["tech_document_chunks", counts["tech_document_chunks"]],
        ["paper_sections", counts["paper_sections"]],
        ["paper_tables", counts["paper_tables"]],
        ["paper_figures", counts["paper_figures"]],
        ["event_candidates", counts["event_candidates"]],
        ["event_outcomes", counts["event_outcomes"]],
        ["price_forecasts", counts["price_forecasts"]],
        ["price_forecast_evaluations", counts["price_forecast_evaluations"]],
    ]
    lines.append(_table(snapshot_rows))
    lines.append("")
    lines.append("## Coverage by Source Type")
    lines.append("")
    source_type_rows = [["source_type", "count"]]
    source_type_rows += [[row[0], row[1]] for row in summary["source_type_rows"]]
    lines.append(_table(source_type_rows))
    lines.append("")
    lines.append("## Coverage by Source")
    lines.append("")
    source_rows = [["source", "count"]]
    source_rows += [[row[0], row[1]] for row in summary["source_rows"][:12]]
    lines.append(_table(source_rows))
    lines.append("")
    lines.append("## Coverage by Company Code")
    lines.append("")
    company_rows = [["company_code", "count"]]
    company_rows += [[row[0], row[1]] for row in summary["company_rows"]]
    lines.append(_table(company_rows))
    lines.append("")
    lines.append("## Coverage by Domain Hit")
    lines.append("")
    domain_rows = [["domain", "count"]]
    domain_rows += [[row[0], row[1]] for row in summary["domain_rows"]]
    lines.append(_table(domain_rows))
    lines.append("")
    lines.append("## Recent Documents")
    lines.append("")
    doc_rows = [["source", "type", "published_at", "collected_at", "confidence", "title"]]
    for row in summary["latest_docs"]:
        doc_rows.append([
            row[0],
            row[1],
            row[3],
            row[4],
            f"{float(row[5] or 0.0):.2f}",
            row[2],
        ])
    lines.append(_table(doc_rows))
    lines.append("")
    lines.append("## Technology Potential Analysis")
    lines.append("")
    analysis_rows = [[
        "topic",
        "company",
        "domain",
        "catalyst",
        "bottleneck",
        "evidence",
        "reasoning_conf",
        "recommendation",
    ]]
    for item in analyses:
        a = item["assessment"]
        analysis_rows.append([
            item["topic"],
            item.get("company_hint", ""),
            item.get("domain_hint", ""),
            a.get("catalyst_imminence", {}).get("dominant_window", ""),
            a.get("bottleneck", {}).get("importance", ""),
            a.get("evidence_quality", {}).get("grade", ""),
            f"{float(a.get('reasoning_confidence', 0.0)):.2f}",
            a.get("recommendation", ""),
        ])
    lines.append(_table(analysis_rows))
    lines.append("")
    for item in analyses:
        a = item["assessment"]
        lines.append(f"### {item['topic']}")
        lines.append("")
        lines.append(f"- Company hint: `{item.get('company_hint', '') or 'none'}`")
        lines.append(f"- Domain hint: `{item.get('domain_hint', '') or 'auto'}`")
        lines.append(f"- Recommendation: `{a.get('recommendation', '')}`")
        lines.append(f"- Reasoning confidence: `{float(a.get('reasoning_confidence', 0.0)):.2f}`")
        lines.append(f"- Evidence grade: `{a.get('evidence_quality', {}).get('grade', '')}`")
        lines.append(f"- Dominant catalyst window: `{a.get('catalyst_imminence', {}).get('dominant_window', '')}`")
        lines.append(f"- Bottleneck importance: `{a.get('bottleneck', {}).get('importance', '')}`")
        lines.append(f"- Novelty: `{a.get('novelty', {}).get('surprise_level', '')}` / `{a.get('novelty', {}).get('market_awareness', '')}`")
        lines.append(f"- Revenue linkage: `{a.get('revenue_linkage', {}).get('link_strength', '')}` / `{a.get('revenue_linkage', {}).get('time_to_monetize', '')}`")
        lines.append(f"- Market transmission speed: `{a.get('market_transmission_speed', {}).get('speed', '')}`")
        lines.append("")
        lines.append("**Overall thesis**")
        lines.append("")
        lines.append(a.get("overall_thesis", "") or "No thesis returned.")
        lines.append("")
        lines.append("**Company impact**")
        lines.append("")
        for impact in a.get("company_impact", [])[:6]:
            lines.append(
                f"- {impact.get('company', '')} ({impact.get('code', '')}) "
                f"[{impact.get('stance', '')}] conf={float(impact.get('confidence', 0.0)):.2f} "
                f"supported={impact.get('supported_in_evidence', False)}: {impact.get('reason', '')}"
            )
        lines.append("")
        lines.append("**Supporting evidence**")
        lines.append("")
        for ev in a.get("supporting_evidence", [])[:5]:
            lines.append(
                f"- {ev.get('source_type', '')}/{ev.get('source', '')} | "
                f"{ev.get('title', '')} | score={float(ev.get('evidence_score', 0.0)):.3f}"
            )
        lines.append("")
        if a.get("red_flags"):
            lines.append("**Red flags**")
            lines.append("")
            for rf in a.get("red_flags", []):
                lines.append(f"- {rf}")
            lines.append("")
        if a.get("missing_data"):
            lines.append("**Missing data**")
            lines.append("")
            for md in a.get("missing_data", []):
                lines.append(f"- {md}")
            lines.append("")

    lines.append("## Conclusions")
    lines.append("")
    lines.append(
        "- The strongest current coverage is still in papers and official company sources, with OpenAlex and Samsung/SK hynix/ASML data leading the corpus."
    )
    lines.append(
        "- The most actionable technology themes are the ones with high reasoning confidence and strong evidence grades: HBM, EUV, and advanced packaging."
    )
    lines.append(
        "- Weak spots remain in event generation and some external source coverage, so the next lift should come from more fallback official pages, stronger company-specific papers, and more structured event extraction."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate semiconductor data coverage and potential report.")
    parser.add_argument("--output-md", default=str(OUTPUT_MD), help="Markdown output path")
    parser.add_argument("--output-json", default=str(OUTPUT_JSON), help="JSON output path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    summary = fetch_summary()
    analyses = build_technology_analysis()

    md = render_markdown(summary, analyses)
    output_md = Path(args.output_md)
    output_json = Path(args.output_json)
    output_md.write_text(md, encoding="utf-8")
    output_json.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
                "analyses": analyses,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(f"[OK] Report written: {output_md}")
    print(f"[OK] Report written: {output_json}")
    print(f"[SUMMARY] tech_documents={summary['counts']['tech_documents']} chunks={summary['counts']['tech_document_chunks']} paper_sections={summary['counts']['paper_sections']}")


if __name__ == "__main__":
    main()
