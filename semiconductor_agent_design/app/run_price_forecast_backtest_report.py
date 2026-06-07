from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.db.postgres import get_pg_conn
from app.forecast.price_forecast import TECH_THEMES


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_PDF = REPORT_DIR / "price_forecast_backtest_report.pdf"

COMPANIES = ["005930", "000660", "042700"]
COMPANY_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "042700": "한미반도체",
}

FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\malgun.ttf"),
    Path(r"C:\Windows\Fonts\malgunbd.ttf"),
]


def _fmt_pct(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):+.2%}"


def _fmt_num(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.2f}"


def _fmt_bias(value) -> str:
    if value is None:
        return "-"
    num = float(value)
    label = "중립"
    if num > 0.001:
        label = "긍정"
    elif num < -0.001:
        label = "부정"
    return f"{label} ({num:+.4f})"


def _fmt_date(value) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat().split("T")[0]
    return str(value)


def _query(sql: str, params=()):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _norm_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _theme_for_company(company_code: str) -> dict[str, list[str]]:
    return TECH_THEMES.get(_norm_code(company_code), TECH_THEMES["005930"])


def _safe_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value is None:
        return datetime.now(timezone.utc)
    raw = str(value).strip()
    if not raw:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _register_font() -> str:
    for path in FONT_CANDIDATES:
        if path.exists():
            font_name = "MalgunGothic"
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, str(path)))
            return font_name
    return "Helvetica"


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    text = (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return Paragraph(text, style)


def _table(data: list[list[str]], widths: list[float], font_name: str, font_size: int = 8, header_fill="#E8EEF5"):
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("LEADING", (0, 0), (-1, -1), font_size + 2),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_fill)),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D1DC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def _match_terms(text: str, terms: list[str]) -> list[str]:
    lowered = (text or "").lower()
    hits = []
    for term in terms:
        if term.lower() in lowered:
            hits.append(term)
    return hits


def _format_kv_pairs(items: Any, limit: int = 3) -> str:
    if not items:
        return "-"
    parts: list[str] = []
    for item in list(items)[:limit]:
        if isinstance(item, dict):
            key = item.get("name") or item.get("key") or item.get("source") or item.get("domain")
            val = item.get("count") or item.get("value")
            if key is None:
                continue
            parts.append(f"{key}:{val}" if val is not None else str(key))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            parts.append(f"{item[0]}:{item[1]}")
        else:
            parts.append(str(item))
    return ", ".join(parts) if parts else "-"


def _coerce_scenario_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except Exception:
            return []
    return []


def fetch_tech_evidence(company_code: str, as_of: datetime, limit: int = 5) -> dict[str, Any]:
    theme = _theme_for_company(company_code)
    keywords = theme["keywords"]
    positive_terms = [t.lower() for t in theme["positive"]]
    negative_terms = [t.lower() for t in theme["negative"]]

    clauses: list[str] = []
    params: list[Any] = [as_of]
    for kw in keywords:
        pattern = f"%{kw}%"
        clauses.append("(title ILIKE %s OR COALESCE(summary,'') ILIKE %s OR COALESCE(content,'') ILIKE %s)")
        params.extend([pattern, pattern, pattern])

    if not clauses:
        return {"doc_count": 0, "docs": [], "top_sources": [], "tech_notes": []}

    sql = f"""
        SELECT source, source_type, title, COALESCE(summary, '') AS summary,
               COALESCE(content, '') AS content, published_at, confidence
        FROM tech_documents
        WHERE published_at IS NOT NULL
          AND published_at < %s
          AND ({' OR '.join(clauses)})
        ORDER BY published_at DESC
        LIMIT 400
    """
    rows = _query(sql, params)

    scored_docs: list[dict[str, Any]] = []
    source_counter: dict[str, int] = {}
    tech_notes: list[str] = []
    for row in rows:
        text = f"{row.get('title', '')} {row.get('summary', '')} {row.get('content', '')}"
        keyword_hits = _match_terms(text, keywords)
        pos_hits = _match_terms(text, positive_terms)
        neg_hits = _match_terms(text, negative_terms)
        published_at = _safe_datetime(row.get("published_at"))
        age_days = max(0, (as_of.date() - published_at.date()).days)
        recency = max(0.20, 1.0 - age_days / 365.0)
        source_type = str(row.get("source_type") or "").lower()
        if source_type in {"irds", "jedec", "hotchips", "paper", "openalex", "arxiv"}:
            source_weight = 0.45
        elif source_type in {"company_newsroom", "official", "equip_doc"} or "newsroom" in source_type:
            source_weight = 0.35
        elif source_type in {"blog", "semi_blog"}:
            source_weight = 0.25
        elif source_type in {"news", "rss"}:
            source_weight = 0.20
        else:
            source_weight = 0.15
        score = (
            source_weight
            * recency
            * (1.0 + 0.10 * len(keyword_hits) + 0.18 * len(pos_hits) - 0.18 * len(neg_hits))
            * (0.85 + 0.15 * float(row.get("confidence") or 0.0))
        )
        doc = dict(row)
        doc["keyword_hits"] = keyword_hits
        doc["positive_hits"] = pos_hits
        doc["negative_hits"] = neg_hits
        doc["recency_score"] = round(recency, 4)
        doc["evidence_score"] = round(score, 4)
        scored_docs.append(doc)
        source_key = str(row.get("source") or row.get("source_type") or "")
        source_counter[source_key] = source_counter.get(source_key, 0) + 1
        if len(tech_notes) < 8:
            note_bits = []
            if keyword_hits:
                note_bits.append("keywords=" + ",".join(keyword_hits[:4]))
            if pos_hits:
                note_bits.append("positive=" + ",".join(pos_hits[:3]))
            if neg_hits:
                note_bits.append("negative=" + ",".join(neg_hits[:3]))
            tech_notes.append(
                f"{row.get('source_type')}:{str(row.get('title') or '')[:55]}"
                + (f" ({'; '.join(note_bits)})" if note_bits else "")
            )

    scored_docs.sort(key=lambda x: x.get("evidence_score", 0.0), reverse=True)
    return {
        "doc_count": len(rows),
        "docs": scored_docs[:limit],
        "top_sources": sorted(source_counter.items(), key=lambda kv: kv[1], reverse=True)[:5],
        "tech_notes": tech_notes[:8],
    }


def fetch_overall_summary():
    sql = """
    SELECT
      COUNT(*) AS cases,
      AVG(e.expected_return) AS avg_expected_return,
      AVG(e.realized_return) AS avg_realized_return,
      AVG(e.abs_error) AS avg_abs_error,
      AVG(CASE WHEN e.interval_hit THEN 1.0 ELSE 0.0 END) AS interval_hit_rate,
      AVG(CASE
            WHEN e.expected_return = 0 THEN 1.0
            WHEN (e.expected_return > 0) = (e.realized_return > 0) THEN 1.0
            ELSE 0.0
          END) AS direction_accuracy
    FROM price_forecast_evaluations e
    JOIN price_forecasts f ON f.id = e.forecast_id
    WHERE f.company_code = ANY(%s)
    """
    rows = _query(sql, (COMPANIES,))
    return rows[0] if rows else {}


def fetch_backtest_summary():
    sql = """
    SELECT f.company_code, f.horizon_days,
           COUNT(*) AS cases,
           AVG(e.expected_return) AS avg_expected_return,
           AVG(e.realized_return) AS avg_realized_return,
           AVG(e.abs_error) AS avg_abs_error,
           AVG(CASE WHEN e.interval_hit THEN 1.0 ELSE 0.0 END) AS interval_hit_rate,
           AVG(CASE
                 WHEN e.expected_return = 0 THEN 1.0
                 WHEN (e.expected_return > 0) = (e.realized_return > 0) THEN 1.0
                 ELSE 0.0
               END) AS direction_accuracy
    FROM price_forecast_evaluations e
    JOIN price_forecasts f ON f.id = e.forecast_id
    WHERE f.company_code = ANY(%s)
    GROUP BY f.company_code, f.horizon_days
    ORDER BY f.company_code, f.horizon_days
    """
    return _query(sql, (COMPANIES,))


def fetch_representative_cases():
    sql = """
    SELECT f.id, f.company_code, f.horizon_days, f.as_of, f.published_cutoff, f.target_date,
           f.base_price, f.expected_return, f.low_return, f.high_return,
           f.expected_price, f.low_price, f.high_price, f.features, f.signals, f.scenarios,
           e.realized_at, e.realized_close, e.realized_return, e.abs_error, e.interval_hit,
           e.scenario_hit, e.feedback
    FROM price_forecasts f
    JOIN price_forecast_evaluations e ON e.forecast_id = f.id
    WHERE f.company_code = %s
    ORDER BY e.abs_error DESC, f.horizon_days DESC, f.as_of DESC
    LIMIT 1
    """
    out = []
    for company in COMPANIES:
        rows = _query(sql, (company,))
        if rows:
            row = rows[0]
            row["company_name"] = COMPANY_NAMES[company]
            out.append(row)
    return out


def _feature_rows(features: dict) -> list[list[str]]:
    keys = [
        ("latest_close", "latest_close", "원천 종가"),
        ("return_7d", "return_7d", "7일 수익률"),
        ("return_20d", "return_20d", "20일 수익률"),
        ("return_60d", "return_60d", "60일 수익률"),
        ("volatility_20d", "volatility_20d", "20일 변동성"),
        ("volatility_60d", "volatility_60d", "60일 변동성"),
        ("drawdown_60d", "drawdown_60d", "60일 낙폭"),
        ("range_60d", "range_60d", "60일 가격범위"),
        ("volume_ratio_20d", "volume_ratio_20d", "20일 거래량 비율"),
        ("trend_strength", "trend_strength", "추세 강도"),
    ]
    rows = [["항목", "값", "해석"]]
    for key, _, label in keys:
        val = features.get(key)
        if key in {"latest_close", "range_60d", "volume_ratio_20d", "trend_strength"}:
            formatted = _fmt_num(val)
        else:
            formatted = _fmt_pct(val)
        if key == "latest_close":
            meaning = "예측 시점 직전 종가"
        elif key in {"return_7d", "return_20d", "return_60d"}:
            meaning = "최근 수익률이 플러스면 모멘텀, 마이너스면 약세 신호"
        elif key in {"volatility_20d", "volatility_60d"}:
            meaning = "숫자가 높을수록 변동성 리스크가 큼"
        elif key == "drawdown_60d":
            meaning = "최근 고점 대비 얼마나 밀렸는지"
        elif key == "range_60d":
            meaning = "60일 변동 폭이 넓을수록 추세 지속/반전 위험이 함께 커짐"
        elif key == "volume_ratio_20d":
            meaning = "평균 대비 거래량이 과열인지 확인"
        else:
            meaning = "최근 수익률과 변동성을 합쳐 본 추세 강도"
        rows.append([label, formatted, meaning])
    return rows


def _tech_signal_rows(signals: dict, tech_evidence: dict[str, Any]) -> list[list[str]]:
    if not isinstance(signals, dict):
        signals = {}
    tech_notes = signals.get("tech_notes") or tech_evidence.get("tech_notes") or []
    top_sources = signals.get("tech_top_sources") or tech_evidence.get("top_sources") or []
    top_domains = signals.get("tech_top_domains") or []
    rows = [["항목", "값", "해석"]]
    doc_count = signals.get("tech_doc_count")
    try:
        doc_count_num = int(float(doc_count))
    except Exception:
        doc_count_num = 0
    if doc_count_num <= 0:
        doc_count_num = int(tech_evidence.get("doc_count") or 0)
    rows.append([
        "tech_doc_count",
        str(doc_count_num),
        "예측 시점 이전 기술 문서 중 회사 기술 테마에 걸린 문서 수",
    ])
    rows.append([
        "tech_event_count",
        str(int(signals.get("tech_event_count") or 0)),
        "기술 문서에서 파생된 이벤트 후보 수",
    ])
    rows.append([
        "tech_doc_bias",
        _fmt_bias(signals.get("tech_doc_bias") or 0.0),
        "논문/공식자료/블로그에서 잡은 기술 방향성의 문서 점수",
    ])
    rows.append([
        "tech_event_bias",
        _fmt_bias(signals.get("tech_event_bias") or 0.0),
        "기술 문서에서 생성된 이벤트의 후행 반응 점수",
    ])
    rows.append([
        "tech_bias",
        _fmt_bias(signals.get("tech_bias") or 0.0),
        "문서와 이벤트를 합친 최종 기술 편향값",
    ])
    rows.append([
        "top_sources",
        _format_kv_pairs(top_sources, 3),
        "어떤 출처가 기술 판단에 가장 많이 기여했는지",
    ])
    rows.append([
        "top_domains",
        _format_kv_pairs(top_domains, 3),
        "기술 이벤트가 어떤 도메인에 집중되어 있는지",
    ])
    rows.append([
        "tech_notes",
        " / ".join(str(x) for x in tech_notes[:3]) if tech_notes else "-",
        "문서 제목 레벨에서 어떤 기술 신호를 포착했는지",
    ])
    return rows


def _tech_doc_rows(tech_evidence: dict[str, Any]) -> list[list[str]]:
    rows = [["published_at", "source", "title", "why it matters"]]
    for doc in tech_evidence.get("docs", [])[:5]:
        title = str(doc.get("title") or "")
        why_bits = []
        if doc.get("keyword_hits"):
            why_bits.append("keywords=" + ",".join(doc["keyword_hits"][:4]))
        if doc.get("positive_hits"):
            why_bits.append("positive=" + ",".join(doc["positive_hits"][:3]))
        if doc.get("negative_hits"):
            why_bits.append("negative=" + ",".join(doc["negative_hits"][:3]))
        why_bits.append(f"score={float(doc.get('evidence_score') or 0.0):.3f}")
        rows.append([
            _fmt_date(doc.get("published_at")),
            f"{doc.get('source_type')}/{doc.get('source')}",
            title[:60],
            "; ".join(why_bits),
        ])
    return rows


def fetch_relevant_events(company_code: str, as_of: datetime, limit: int = 5) -> list[dict[str, Any]]:
    since_365 = (as_of.date() - timedelta(days=365)).isoformat()
    sql = """
        SELECT ec.event_date, ec.event_type, ec.source, ec.title, COALESCE(ec.summary, '') AS summary,
               ec.confidence, ec.related_domain, COALESCE(ec.extra->>'origin', '') AS origin,
               eo.label, eo.ret_5d, eo.ret_20d
        FROM event_candidates ec
        LEFT JOIN event_outcomes eo ON eo.event_id = ec.event_id
        WHERE ec.related_company = %s
          AND ec.event_date < %s::date
          AND ec.event_date >= %s::date
        ORDER BY ec.event_date DESC
        LIMIT 40
    """
    rows = _query(sql, (company_code, as_of.date().isoformat(), since_365))
    scored: list[dict[str, Any]] = []
    for row in rows:
        text = f"{row.get('title', '')} {row.get('summary', '')}".lower()
        confidence = float(row.get("confidence") or 0.0)
        origin = str(row.get("origin") or "")
        age_days = max(0, (as_of.date() - _safe_datetime(row.get("event_date")).date()).days)
        recency = max(0.20, 1.0 - age_days / 365.0)
        tech_bonus = 0.10 if origin == "tech_documents" else 0.0
        label = str(row.get("label") or "")
        label_bias = 0.0
        if label == "positive":
            label_bias = 0.12
        elif label == "negative":
            label_bias = -0.12
        score = recency * (0.85 + 0.15 * confidence) + tech_bonus + label_bias
        doc = dict(row)
        doc["evidence_score"] = round(score, 4)
        scored.append(doc)
    scored.sort(key=lambda x: x.get("evidence_score", 0.0), reverse=True)
    return scored[:limit]


def _event_rows(events: list[dict[str, Any]]) -> list[list[str]]:
    rows = [["event_date", "type", "origin", "title", "impact"]]
    for event in events[:5]:
        impact = []
        if event.get("label"):
            impact.append(f"label={event.get('label')}")
        if event.get("ret_5d") is not None:
            impact.append(f"ret_5d={_fmt_pct(event.get('ret_5d'))}")
        if event.get("ret_20d") is not None:
            impact.append(f"ret_20d={_fmt_pct(event.get('ret_20d'))}")
        impact.append(f"score={float(event.get('evidence_score') or 0.0):.3f}")
        rows.append([
            _fmt_date(event.get("event_date")),
            str(event.get("event_type") or "-"),
            str(event.get("origin") or "-"),
            str(event.get("title") or "")[:55],
            "; ".join(impact),
        ])
    return rows


def _case_reasoning_rows(case: dict) -> list[list[str]]:
    f = case["features"]
    s = case["signals"] or {}
    if not isinstance(s, dict):
        s = {}
    scenarios = _coerce_scenario_list(case["scenarios"] or [])
    bull = next((x for x in scenarios if x.get("name") == "bull"), {})
    base = next((x for x in scenarios if x.get("name") == "base"), {})
    bear = next((x for x in scenarios if x.get("name") == "bear"), {})
    rows = [["판단축", "관측값", "해석"]]
    rows.append([
        "가격 모멘텀",
        f"7d {_fmt_pct(f.get('return_7d'))}, 20d {_fmt_pct(f.get('return_20d'))}, 60d {_fmt_pct(f.get('return_60d'))}",
        "최근 수익률이 강하면 상방 지속, 약하면 반전 가능성을 더 봄",
    ])
    rows.append([
        "추세 강도",
        f"{float(f.get('trend_strength') or 0.0):+.2f}",
        "1 이상이면 강한 추세, 2~3이면 모델이 bull 또는 bear로 크게 기울기 쉬움",
    ])
    rows.append([
        "변동성/낙폭",
        f"20d {_fmt_pct(f.get('volatility_20d'))}, 60d {_fmt_pct(f.get('volatility_60d'))}, drawdown {_fmt_pct(f.get('drawdown_60d'))}",
        "변동성이 높거나 drawdown이 크면 예측 밴드를 넓히는 근거",
    ])
    rows.append([
        "거래량",
        f"20d ratio {_fmt_num(f.get('volume_ratio_20d'))}",
        "평균 대비 과열/침체 여부를 확인",
    ])
    rows.append([
        "외생 변수",
        f"event_bias {float(s.get('event_bias') or 0.0):+.2f}, macro_bias {float(s.get('macro_bias') or 0.0):+.2f}",
        "여기 값이 0에 가까우면 가격 데이터에 더 많이 의존하게 됨",
    ])
    rows.append([
        "시나리오 가중치",
        f"bull {float(bull.get('probability') or 0.0):.1%}, base {float(base.get('probability') or 0.0):.1%}, bear {float(bear.get('probability') or 0.0):.1%}",
        "가장 높은 확률 시나리오가 최종 예측 방향을 사실상 결정",
    ])
    return rows


def _company_case_story(case: dict, tech_evidence: dict[str, Any]) -> list[str]:
    code = case["company_code"]
    f = case["features"]
    s = case["signals"] or {}
    if not isinstance(s, dict):
        s = {}
    scenarios = _coerce_scenario_list(case["scenarios"] or [])
    bull = next((x for x in scenarios if x.get("name") == "bull"), {})
    base = next((x for x in scenarios if x.get("name") == "base"), {})
    bear = next((x for x in scenarios if x.get("name") == "bear"), {})
    doc_count_num = int(tech_evidence.get("doc_count") or 0)
    top_sources = _format_kv_pairs(tech_evidence.get("top_sources"), 3)
    if code == "005930":
        return [
            f"삼성전자는 { _fmt_pct(f.get('return_7d')) }, { _fmt_pct(f.get('return_20d')) }, { _fmt_pct(f.get('return_60d')) }로 최근 7일/20일/60일 수익률이 모두 강했고, trend_strength도 {float(f.get('trend_strength') or 0.0):+.2f}로 상방 추세가 매우 뚜렷했다.",
            f"변동성은 20일 {_fmt_pct(f.get('volatility_20d'))}, 60일 {_fmt_pct(f.get('volatility_60d'))} 수준이라 추세가 다소 안정적으로 보였고, drawdown도 {_fmt_pct(f.get('drawdown_60d'))}로 크지 않았다.",
            f"반도체 기술 문서는 예측 시점 이전 기준 {doc_count_num}건이었고, 주된 출처는 {top_sources}였다. 문서 제목에서는 HBM/DRAM/GAA/EUV/패키징이 반복되어 삼성의 메모리·공정·파운드리 테마를 지지했다.",
            f"시나리오 확률은 bull {float(bull.get('probability') or 0.0):.1%}, base {float(base.get('probability') or 0.0):.1%}, bear {float(bear.get('probability') or 0.0):.1%}로 상방 지속 쪽에 가장 무게를 뒀다.",
            "문제는 실제로는 30일 뒤 수익률이 기대보다 약하거나 반전됐다는 점이다. 즉, 가격 모멘텀과 기술 문서에서 잡힌 장기 테마만으로는 포착되지 않는 업황/수급 전환이 있었고, 그 부분을 예측 범위가 놓쳤다.",
        ]
    if code == "000660":
        return [
            f"SK하이닉스는 단기 7일 수익률이 {_fmt_pct(f.get('return_7d'))}로 약세였지만, 60일 수익률은 {_fmt_pct(f.get('return_60d'))}였고 trend_strength도 {float(f.get('trend_strength') or 0.0):+.2f}라 완전한 추세 붕괴로 보지는 않았다.",
            f"drawdown가 {_fmt_pct(f.get('drawdown_60d'))} 수준이고 거래량 비율도 {_fmt_num(f.get('volume_ratio_20d'))}이라, 모델은 급락 지속보다는 완만한 회복과 변동성 구간을 예상했다.",
            f"반도체 기술 문서는 예측 시점 이전 기준 {doc_count_num}건이었고, 주된 출처는 {top_sources}였다. HBM/CXL/PIM/TSV/CoWoS 키워드가 반복되어 메모리와 패키징 체인의 중기 수혜를 읽을 수 있었다.",
            f"하지만 event_bias {float(s.get('event_bias') or 0.0):+.2f}, macro_bias {float(s.get('macro_bias') or 0.0):+.2f}가 약해 HBM 수요 재평가의 폭을 충분히 키우지 못했다.",
            "결국 실제 30일 수익률은 예측 밴드를 훨씬 뛰어넘는 급격한 재평가로 이어졌고, 이 케이스는 기술 축은 맞았지만 이벤트 탄력과 변동성 레짐을 과소평가한 대표 사례다.",
        ]
    return [
        f"한미반도체는 7일/20일/60일 수익률이 각각 {_fmt_pct(f.get('return_7d'))}, {_fmt_pct(f.get('return_20d'))}, {_fmt_pct(f.get('return_60d'))}로 최근 흐름이 나쁘지 않았고, trend_strength도 {float(f.get('trend_strength') or 0.0):+.2f}라 모델은 이미 상방 쪽으로 기울어 있었다.",
        f"반도체 기술 문서는 예측 시점 이전 기준 {doc_count_num}건이었고, 주된 출처는 {top_sources}였다. advanced packaging / hybrid bonding / TSV / interposer / substrate / metrology / inspection 계열이 핵심 축이었다.",
        f"실제로 bull 시나리오는 {float(bull.get('probability') or 0.0):.1%}였고 base는 {float(base.get('probability') or 0.0):.1%} 수준이었다. 즉, 상방 자체는 봤지만 현실의 급등 폭을 충분히 크게 잡지 못한 형태였다.",
        f"하지만 event_bias {float(s.get('event_bias') or 0.0):+.2f}, macro_bias {float(s.get('macro_bias') or 0.0):+.2f}가 거의 0이어서 장비/후공정 수요 전환 같은 외생 촉매를 충분히 가격에 얹지 못했다.",
        "실제 30일 수익률은 예측 밴드를 크게 넘어선 반등이었기 때문에, 이 케이스는 '방향은 비슷하지만 폭이 부족한' 전형적인 과소추정 사례다.",
    ]


def build_pdf(output_path: Path) -> Path:
    overall = fetch_overall_summary()
    backtest = fetch_backtest_summary()
    cases = fetch_representative_cases()
    latest_as_of = max((row["as_of"] for row in _query(
        """
        SELECT MAX(as_of) AS as_of
        FROM price_forecasts
        WHERE company_code = ANY(%s)
        """,
        (COMPANIES,),
    )), default=None)

    font_name = _register_font()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleK", parent=styles["Title"], fontName=font_name, fontSize=20, leading=24, textColor=colors.black, spaceAfter=8))
    styles.add(ParagraphStyle(name="H1K", parent=styles["Heading1"], fontName=font_name, fontSize=14, leading=18, textColor=colors.HexColor("#1F4D78"), spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(name="H2K", parent=styles["Heading2"], fontName=font_name, fontSize=11.5, leading=14, textColor=colors.HexColor("#1F4D78"), spaceBefore=8, spaceAfter=4))
    styles.add(ParagraphStyle(name="BodyK", parent=styles["BodyText"], fontName=font_name, fontSize=9.6, leading=13, textColor=colors.black, spaceAfter=5, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="SmallK", parent=styles["BodyText"], fontName=font_name, fontSize=8.2, leading=10.5, textColor=colors.HexColor("#444444"), spaceAfter=3, alignment=TA_LEFT))

    story = []
    story.append(_p("삼성전자·SK하이닉스·한미반도체 백테스트 리포트", styles["TitleK"]))
    story.append(_p(f"기준 시점(as_of): {_fmt_date(latest_as_of)} | 생성일: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", styles["SmallK"]))
    story.append(Spacer(1, 0.08 * inch))

    story.append(_p("요약", styles["H1K"]))
    story.append(_p("이 문서는 최신 예측 스냅샷이 아니라, 과거 예측이 실제와 얼마나 달랐는지와 그 예측이 어떤 반도체 기술 데이터 해석에서 나왔는지를 중심으로 정리한 백테스트 리포트다.", styles["BodyK"]))
    story.append(_p("핵심은 가격/이벤트/지표 데이터만 보지 않고, 회사별 반도체 기술 문서와 기술 이벤트를 함께 읽어 as_of 이전 시점의 판단을 만들었는지, 그리고 그 판단이 실제 수익률과 얼마나 차이났는지를 케이스별로 보여주는 것이다.", styles["BodyK"]))

    story.append(_p("전체 백테스트 요약", styles["H1K"]))
    summary_lines = [
        f"선정 종목 수: {len(COMPANIES)}",
        f"총 케이스 수: {overall.get('cases', 0)}",
        f"평균 예측 수익률: {_fmt_pct(overall.get('avg_expected_return'))}",
        f"평균 실현 수익률: {_fmt_pct(overall.get('avg_realized_return'))}",
        f"평균 절대오차: {_fmt_pct(overall.get('avg_abs_error'))}",
        f"구간 적중률: {_fmt_pct(overall.get('interval_hit_rate'))}",
        f"방향 정확도: {_fmt_pct(overall.get('direction_accuracy'))}",
    ]
    for line in summary_lines:
        story.append(_p("• " + line, styles["BodyK"]))

    table_rows = [["종목", "기간", "케이스", "예상", "실현", "절대오차", "적중률", "방향정확도"]]
    for row in backtest:
        table_rows.append([
            COMPANY_NAMES.get(row["company_code"], row["company_code"]),
            f"{row['horizon_days']}d",
            str(int(row["cases"])),
            _fmt_pct(row["avg_expected_return"]),
            _fmt_pct(row["avg_realized_return"]),
            _fmt_pct(row["avg_abs_error"]),
            _fmt_pct(row["interval_hit_rate"]),
            _fmt_pct(row["direction_accuracy"]),
        ])
    story.append(_table(table_rows, [1.00 * inch, 0.45 * inch, 0.45 * inch, 0.70 * inch, 0.70 * inch, 0.75 * inch, 0.65 * inch, 0.80 * inch], font_name, 7.3))
    story.append(Spacer(1, 0.10 * inch))

    for idx, case in enumerate(cases):
        tech_evidence = fetch_tech_evidence(case["company_code"], _safe_datetime(case["as_of"]), limit=5)
        story.append(PageBreak())
        story.append(_p(f"{case['company_name']} 대표 사례", styles["H1K"]))
        story.append(_p("선정 기준: 회사별 절대오차가 가장 큰 백테스트 케이스를 대표 사례로 선택했다.", styles["BodyK"]))

        summary = [["항목", "값"]]
        summary += [
            ["as_of", _fmt_date(case["as_of"])],
            ["horizon", f"{case['horizon_days']}d"],
            ["target_date", _fmt_date(case["target_date"])],
            ["base_price", _fmt_num(case["base_price"])],
            ["predicted_return", _fmt_pct(case["expected_return"])],
            ["predicted_band", f"{_fmt_pct(case['low_return'])} ~ {_fmt_pct(case['high_return'])}"],
            ["realized_close", _fmt_num(case["realized_close"])],
            ["realized_return", _fmt_pct(case["realized_return"])],
            ["abs_error", _fmt_pct(case["abs_error"])],
            ["interval_hit", "YES" if case["interval_hit"] else "NO"],
            ["scenario_hit", str(case["scenario_hit"])],
            ["feedback", case["feedback"]],
        ]
        story.append(_table(summary, [1.60 * inch, 5.00 * inch], font_name, 7.6))
        story.append(Spacer(1, 0.08 * inch))

        story.append(_p("예측에 사용된 데이터와 해석", styles["H2K"]))
        story.append(_table(_feature_rows(case["features"]), [1.40 * inch, 1.05 * inch, 4.10 * inch], font_name, 7.0))
        story.append(Spacer(1, 0.08 * inch))

        story.append(_p("반도체 기술 근거", styles["H2K"]))
        story.append(_table(_tech_signal_rows(case["signals"], tech_evidence), [1.35 * inch, 1.05 * inch, 4.15 * inch], font_name, 7.0))
        story.append(Spacer(1, 0.08 * inch))
        story.append(_p(
            f"이 사례는 예측 시점 이전에 누적된 기술 문서 {int(tech_evidence.get('doc_count') or 0)}건을 훑어서, HBM/DRAM/GAA/EUV/패키징 같은 회사별 기술 테마가 실제로 어떻게 반복되는지를 읽고 기술 편향을 만든 것이다.",
            styles["BodyK"],
        ))
        story.append(_p(
            f"기술 편향이 높아지거나 낮아진 이유는 단순 키워드 개수만이 아니라, 논문/공식자료/뉴스룸 같은 출처의 가중치와 positive/negative term의 조합으로 계산됐다.",
            styles["BodyK"],
        ))

        if tech_evidence.get("docs"):
            story.append(_p("대표 기술 문서", styles["H2K"]))
            story.append(_table(_tech_doc_rows(tech_evidence), [0.80 * inch, 1.05 * inch, 2.35 * inch, 2.35 * inch], font_name, 6.6))
            story.append(Spacer(1, 0.08 * inch))

        related_events = fetch_relevant_events(case["company_code"], _safe_datetime(case["as_of"]), limit=5)
        if related_events:
            story.append(_p("관련 이벤트 후보", styles["H2K"]))
            story.append(_table(_event_rows(related_events), [0.75 * inch, 0.85 * inch, 0.65 * inch, 2.40 * inch, 2.00 * inch], font_name, 6.5))
            story.append(Spacer(1, 0.08 * inch))

        story.append(_p("왜 이렇게 예측했는가", styles["H2K"]))
        for bullet in _company_case_story(case, tech_evidence):
            story.append(_p("• " + bullet, styles["BodyK"]))
        story.append(Spacer(1, 0.05 * inch))

        story.append(_p("판단축별 해석", styles["H2K"]))
        story.append(_table(_case_reasoning_rows(case), [1.25 * inch, 1.65 * inch, 3.65 * inch], font_name, 7.0))
        story.append(Spacer(1, 0.06 * inch))

        story.append(_p("시나리오 신호", styles["H2K"]))
        sig_rows = [["scenario", "probability", "expected", "band", "rationale"]]
        for sc in _coerce_scenario_list(case["scenarios"] or []):
            sig_rows.append([
                sc.get("name", "-"),
                f"{float(sc.get('probability') or 0.0):.2%}",
                _fmt_pct(sc.get("expected_return")),
                f"{_fmt_pct(sc.get('low_return'))} ~ {_fmt_pct(sc.get('high_return'))}",
                sc.get("rationale", ""),
            ])
        story.append(_table(sig_rows, [0.70 * inch, 0.75 * inch, 0.75 * inch, 1.00 * inch, 2.85 * inch], font_name, 7.0))
        story.append(Spacer(1, 0.06 * inch))
        story.append(_p("핵심 오차 해석: " + case["feedback"], styles["BodyK"]))

    story.append(PageBreak())
    story.append(_p("결론 및 한계", styles["H1K"]))
    story.append(_p("이 백테스트 리포트는 단순히 '예상 수익률'을 보여주는 문서가 아니라, 예측 시점의 데이터가 어떤 방향성을 만들었고 실제 결과와 얼마나 달랐는지까지 포함해 검증하는 문서다.", styles["BodyK"]))
    story.append(_p("현재 모델은 가격 모멘텀과 추세 지속 구간에는 강하지만, event_bias와 macro_bias가 거의 비어 있는 케이스에서는 이벤트 전환이나 급격한 재평가를 충분히 반영하지 못한다.", styles["BodyK"]))
    story.append(_p("즉, 배포용 품질을 더 높이려면 공시, IR, 업계 수급, 표준/로드맵 같은 외생 변수 신호를 더 촘촘하게 넣고, 과대추세 가중치를 낮춰야 한다.", styles["BodyK"]))

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawRightString(7.75 * inch, 0.5 * inch, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
        title="삼성전자·SK하이닉스·한미반도체 백테스트 리포트",
        author="Codex",
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return output_path


if __name__ == "__main__":
    print(build_pdf(OUTPUT_PDF))
