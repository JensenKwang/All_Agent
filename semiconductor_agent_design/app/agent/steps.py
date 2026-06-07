"""
Core 5-step pipeline for the semiconductor intelligence agent:
1. Collect context with RAG
2. Evaluate the technical claim
3. Map competitive impact
4. Estimate expected value
5. Check market reaction / priced-in status
"""

from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timezone

from app.agent.llm import call_llm_json
from app.agent.models import (
    CompetitiveMap,
    ExpectedValue,
    MarketCheck,
    TechContext,
    TechEvaluation,
    TechEvent,
)
from app.rag.evidence_builder import build_evidence_pack

_log = logging.getLogger(__name__)

COMPANY_MAP = {
    "005930": "Samsung Electronics",
    "000660": "SK hynix",
    "042700": "Hanmi Semiconductor",
    "NVDA": "NVIDIA",
    "TSM": "TSMC",
    "ASML": "ASML",
    "AMAT": "Applied Materials",
    "LRCX": "Lam Research",
    "KLAC": "KLA",
    "MU": "Micron",
    "INTC": "Intel",
}


def _safe_text(value: Any, limit: int = 2000) -> str:
    text = str(value or "")
    return text[:limit]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def context_collect(event: TechEvent) -> TechContext:
    """Collect relevant RAG evidence for the event."""
    _log.info("context_collect | %s", event.title[:80])
    query = f"{event.title} {event.content[:250]}".strip()
    pack = build_evidence_pack(
        query,
        company=event.company_hint or None,
        top_k=8,
    )
    chunks = [
        item.payload
        | {
            "evidence_score": item.evidence_score,
            "evidence_reasons": item.reasons,
        }
        for item in pack.items
    ]
    context_text = (
        f"[Evidence coverage]\n{pack.coverage}\n\n"
        f"{pack.context_text(max_chars=6000)}"
    )
    return TechContext(event=event, as_of=_now_iso(), related_chunks=chunks, context_text=context_text)


def tech_evaluate(ctx: TechContext) -> TechEvaluation:
    """Evaluate the technical claim with the LLM."""
    _log.info("tech_evaluate")
    system = """You are a semiconductor expert and technical analyst.
Reason step by step internally, but output only concise JSON.
Return JSON only, with this schema:
{
  "innovation_score": 1-5,
  "trl": 1-9,
  "reproducibility": "high"|"medium"|"low",
  "prior_art_exists": true|false,
  "key_claims": ["..."],
  "summary": "2-3 sentences"
}"""

    user = f"""[Event]
Title: {ctx.event.title}
Source: {ctx.event.source_type} / {ctx.event.source}
Published: {ctx.event.published_at}

[Content]
{_safe_text(ctx.event.content, 2000)}

[RAG evidence]
{_safe_text(ctx.context_text, 3000)}"""

    data = call_llm_json(system, user)
    return TechEvaluation(
        innovation_score=int(data.get("innovation_score", 3)),
        trl=int(data.get("trl", 4)),
        reproducibility=str(data.get("reproducibility", "medium")),
        prior_art_exists=bool(data.get("prior_art_exists", False)),
        key_claims=list(data.get("key_claims", []) or []),
        summary=str(data.get("summary", "")),
        as_of=ctx.as_of,
    )


def competitive_map(ctx: TechContext, eval: TechEvaluation) -> CompetitiveMap:
    """Map beneficiary and threat companies."""
    _log.info("competitive_map")
    system = """You are a semiconductor expert and market analyst.
Reason step by step internally, but output only concise JSON.
Return JSON only, with this schema:
{
  "beneficiaries": [{"company": "...", "code": "...", "reason": "..."}],
  "threats": [{"company": "...", "code": "...", "reason": "..."}],
  "ripple_effects": ["..."],
  "competitive_summary": "3-4 sentences"
}"""
    user = f"""[Event]
{ctx.event.title}

[Technical evaluation]
Innovation: {eval.innovation_score}/5
TRL: {eval.trl}/9
Claims: {', '.join(eval.key_claims)}
Summary: {eval.summary}

[Evidence]
{_safe_text(ctx.context_text, 2000)}

[Known company codes]
005930 Samsung Electronics
000660 SK hynix
042700 Hanmi Semiconductor
TSM TSMC
NVDA NVIDIA
ASML ASML
AMAT Applied Materials
LRCX Lam Research"""
    data = call_llm_json(system, user)
    return CompetitiveMap(
        beneficiaries=list(data.get("beneficiaries", []) or []),
        threats=list(data.get("threats", []) or []),
        ripple_effects=list(data.get("ripple_effects", []) or []),
        competitive_summary=str(data.get("competitive_summary", "")),
        as_of=ctx.as_of,
    )


def calc_expected_value(eval: TechEvaluation, competitive: CompetitiveMap) -> ExpectedValue:
    """Estimate expected value from technical and market factors."""
    _log.info("calc_expected_value")
    system = """You are a semiconductor strategist.
Reason step by step internally, but output only concise JSON.
Return JSON only, with this schema:
{
  "p_realization": 0.0-1.0,
  "p_benefit": 0.0-1.0,
  "impact_magnitude": "small"|"medium"|"large"|"transformative",
  "time_horizon": "short"|"mid"|"long",
  "ev_score": "low"|"medium"|"high"|"very_high",
  "rationale": "3-4 sentences"
}"""
    user = f"""[Technical evaluation]
Innovation: {eval.innovation_score}/5
TRL: {eval.trl}/9
Reproducibility: {eval.reproducibility}
Prior art exists: {eval.prior_art_exists}
Claims: {', '.join(eval.key_claims)}

[Competitive map]
Beneficiaries: {[b.get('company', '') + ' - ' + b.get('reason', '') for b in competitive.beneficiaries]}
Threats: {[t.get('company', '') + ' - ' + t.get('reason', '') for t in competitive.threats]}
Summary: {competitive.competitive_summary}"""
    data = call_llm_json(system, user)
    return ExpectedValue(
        p_realization=float(data.get("p_realization", 0.5)),
        p_benefit=float(data.get("p_benefit", 0.5)),
        impact_magnitude=str(data.get("impact_magnitude", "medium")),
        time_horizon=str(data.get("time_horizon", "mid")),
        ev_score=str(data.get("ev_score", "medium")),
        rationale=str(data.get("rationale", "")),
        as_of=_now_iso(),
    )


def _company_name(code: str) -> str:
    code = str(code or "").strip().upper()
    return COMPANY_MAP.get(code, code)


def _get_company_price_changes(codes: list[str]) -> list[dict[str, float | str]]:
    """Return recent 5d price changes for the given company codes."""
    normalized = sorted({str(c).strip().upper() for c in codes if str(c).strip()})
    if not normalized:
        return []

    try:
        from app.db.postgres import get_pg_conn

        sql = """
            WITH latest AS (
                SELECT DISTINCT ON (company_code)
                    company_code, close
                FROM price_daily
                WHERE company_code = ANY(%s)
                  AND trade_date >= CURRENT_DATE - INTERVAL '7 days'
                ORDER BY company_code, trade_date DESC
            ),
            oldest AS (
                SELECT DISTINCT ON (company_code)
                    company_code, close
                FROM price_daily
                WHERE company_code = ANY(%s)
                  AND trade_date >= CURRENT_DATE - INTERVAL '7 days'
                ORDER BY company_code, trade_date ASC
            )
            SELECT
                latest.company_code,
                (latest.close - oldest.close) / NULLIF(oldest.close, 0) * 100 AS change_pct
            FROM latest
            JOIN oldest USING (company_code)
            ORDER BY ABS((latest.close - oldest.close) / NULLIF(oldest.close, 0) * 100) DESC
        """
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (normalized, normalized))
                rows = cur.fetchall()

        result: list[dict[str, float | str]] = []
        for code, change_pct in rows or []:
            if change_pct is None:
                continue
            change_pct = float(change_pct)
            result.append(
                {
                    "code": str(code),
                    "company": _company_name(str(code)),
                    "change_pct": change_pct,
                    "direction": "up" if change_pct > 0 else "down" if change_pct < 0 else "flat",
                }
            )
        return result
    except Exception as e:
        _log.warning("price change lookup failed: %s", e)
        return []


def _get_recent_price_change(codes: list[str]) -> float:
    """Return the average 5d price change for the given codes."""
    changes = _get_company_price_changes(codes)
    values = [float(item["change_pct"]) for item in changes if item.get("change_pct") is not None]
    return sum(values) / len(values) if values else 0.0


def _judge_priced_in(ev_score: str, price_change: float) -> bool:
    """Simple priced-in heuristic."""
    thresholds = {
        "very_high": 5.0,
        "high": 3.0,
        "medium": 1.5,
        "low": 0.5,
    }
    threshold = thresholds.get(ev_score, 2.0)
    return price_change >= threshold


def market_check(
    event: TechEvent,
    ev: ExpectedValue,
    competitive: CompetitiveMap,
) -> MarketCheck:
    """Determine whether the event looks priced in and how it may affect stocks."""
    _log.info("market_check")

    benefit_codes = [
        str(b.get("code", "")).strip().upper()
        for b in competitive.beneficiaries
        if str(b.get("code", "")).strip()
    ]
    threat_codes = [
        str(t.get("code", "")).strip().upper()
        for t in competitive.threats
        if str(t.get("code", "")).strip()
    ]

    benefit_moves = _get_company_price_changes(benefit_codes)
    threat_moves = _get_company_price_changes(threat_codes)
    price_change = _get_recent_price_change(benefit_codes or threat_codes)
    already_priced = _judge_priced_in(ev.ev_score, price_change)

    if ev.ev_score in ("high", "very_high") and not already_priced:
        signal = "buy_signal"
    elif already_priced:
        signal = "caution"
    else:
        signal = "neutral"

    top_benefits = ", ".join(
        f"{item['company']}({item['code']}) {float(item['change_pct']):+.1f}%"
        for item in benefit_moves[:3]
    ) or "none"
    top_threats = ", ".join(
        f"{item['company']}({item['code']}) {float(item['change_pct']):+.1f}%"
        for item in threat_moves[:3]
    ) or "none"

    thesis = (
        f"Beneficiary average 5d move is {price_change:+.1f}%. "
        f"EV grade is {ev.ev_score.upper()}. "
        f"Time horizon is {ev.time_horizon}. "
        f"Market reaction looks {'mostly priced in' if already_priced else 'not fully priced in yet'}."
    )
    note = (
        f"Beneficiary average 5d move: {price_change:+.1f}%\n"
        f"Top beneficiaries: {top_benefits}\n"
        f"Top threats: {top_threats}\n"
        f"Priced-in vs EV({ev.ev_score}): {'priced in' if already_priced else 'not yet priced in'}"
    )

    company_moves = [
        {**item, "role": "beneficiary"} for item in benefit_moves
    ] + [
        {**item, "role": "threat"} for item in threat_moves
    ]

    return MarketCheck(
        already_priced_in=already_priced,
        price_change_pct=price_change,
        signal=signal,
        note=note,
        time_horizon=ev.time_horizon,
        company_moves=company_moves,
        thesis=thesis,
        as_of=_now_iso(),
    )
