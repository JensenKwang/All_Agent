"""
신뢰도 점수 계산 모듈
final_score = press(40%) + reporter(30%) + freshness(20%) + sentiment_neutrality(10%)
"""
from datetime import datetime, date
from database import SessionLocal
from models import News, Press, Reporter, ReliabilityLog

# ── 언론사 초기 신뢰도 점수 ────────────────────────────────────────────────────
PRESS_INITIAL_SCORES = {
    # 통신사
    "연합뉴스": 90, "뉴시스": 75, "news1.kr": 72, "newsis.com": 75,
    # 경제지
    "한국경제": 78, "매일경제": 78, "서울경제": 75, "이데일리": 72,
    "아시아경제": 70, "머니투데이": 70, "파이낸셜뉴스": 68,
    "edaily.co.kr": 72, "mk.co.kr": 78, "hankyung.com": 78,
    "sedaily.com": 75, "asiae.co.kr": 70, "view.asiae.co.kr": 70,
    "fnnews.com": 68, "newspim.com": 68, "mt.co.kr": 70,
    # 종합일간지
    "조선일보": 80, "동아일보": 80, "중앙일보": 80,
    "한겨레": 78, "경향신문": 78, "한국일보": 75,
    "chosun.com": 80, "Chosunbiz": 78, "donga.com": 80,
    "hani.co.kr": 78, "khan.co.kr": 78, "hankookilbo.com": 75,
    "joins.com": 80, "joongang.co.kr": 80,
    # IT/전문지
    "전자신문": 80, "디지털타임스": 72,
    "etnews.com": 80, "dt.co.kr": 72, "ddaily.co.kr": 72,
    "thelec.kr": 78, "zdnet.co.kr": 72, "bloter.net": 70,
    "ZDNet Korea": 72,
    # 방송사
    "MBC뉴스": 80, "SBS뉴스": 80, "KBS": 82, "JTBC": 78, "YTN": 75,
    "MBC뉴스": 80, "SBS뉴스": 80, "KBS뉴스": 82,
    "news.jtbc.co.kr": 78, "ytn.co.kr": 75,
    # 경제TV
    "머니투데이방송": 70, "한국경제TV": 72,
}

DEFAULT_PRESS_SCORE = 55  # 목록에 없는 언론사 기본값


# ── 개별 점수 계산 함수들 ──────────────────────────────────────────────────────

def calc_press_score(press: Press) -> float:
    """언론사 신뢰도 점수 반환 (DB 값 우선, 없으면 초기값 적용)"""
    if press is None:
        return DEFAULT_PRESS_SCORE
    # 초기값(50)이면 사전값으로 덮어쓰기
    if press.reliability_score == 50:
        score = PRESS_INITIAL_SCORES.get(press.name, DEFAULT_PRESS_SCORE)
        press.reliability_score = score
    return float(press.reliability_score)


def calc_reporter_score(reporter: Reporter, press: Press) -> float:
    """
    기자 신뢰도:
    - Unknown 기자: 언론사 점수의 80%
    - 실명 기자: 언론사 점수 × 0.9 + 이메일 보너스 5점 - 정정 1건당 15점 감점
    - 하한 10
    """
    press_score = calc_press_score(press)

    if reporter is None or reporter.name in ("Unknown", "알 수 없음"):
        return float(round(press_score * 0.8, 2))

    base = press_score * 0.9
    email_bonus = 5 if reporter.email else 0
    correction_penalty = (reporter.correction_count or 0) * 15
    score = base + email_bonus - correction_penalty
    return float(max(10, round(score, 2)))


def calc_freshness(pub_date_str: str) -> float:
    """게재일 기준 최신성 점수"""
    if not pub_date_str:
        return 50.0
    try:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                dt = datetime.strptime(pub_date_str[:25], fmt)
                pub = dt.date() if hasattr(dt, "date") else dt
                break
            except ValueError:
                continue
        else:
            return 50.0

        if hasattr(pub, "date"):
            pub = pub.date()
        days = (date.today() - pub).days

        if days <= 1:   return 100.0
        elif days <= 7:  return 85.0
        elif days <= 14: return 70.0
        elif days <= 30: return 50.0
        else:            return 25.0
    except Exception:
        return 50.0


def calc_sentiment_neutrality(sentiment_score) -> float:
    """감성 점수 중립성: 극단적 편향(-100~100)일수록 감점"""
    if sentiment_score is None:
        return 70.0  # 미측정 시 중간값
    # 절댓값이 클수록(극단적) 점수 낮음
    return float(max(0, 100 - abs(sentiment_score) * 0.5))


# ── 최종 신뢰도 계산 ──────────────────────────────────────────────────────────

def calc_final_score(press_s, reporter_s, freshness_s, sentiment_s) -> float:
    return round(
        press_s      * 0.35 +
        reporter_s   * 0.30 +
        freshness_s  * 0.25 +
        sentiment_s  * 0.10,
        2
    )


# ── DB 반영 ───────────────────────────────────────────────────────────────────

def compute_and_save(news: News, db) -> float:
    """뉴스 1건의 신뢰도를 계산하고 ReliabilityLog에 저장, final_score 반환"""
    p_score = calc_press_score(news.press)
    r_score = calc_reporter_score(news.reporter, news.press)
    f_score = calc_freshness(news.pub_date)
    s_score = calc_sentiment_neutrality(news.sentiment_score)
    final   = calc_final_score(p_score, r_score, f_score, s_score)

    # 기존 로그가 있으면 덮어쓰기
    log = db.query(ReliabilityLog).filter_by(news_id=news.id).first()
    if log:
        log.press_score    = p_score
        log.reporter_score = r_score
        log.freshness      = f_score
        log.sentiment_score = s_score
        log.final_score    = final
    else:
        db.add(ReliabilityLog(
            news_id        = news.id,
            press_score    = p_score,
            reporter_score = r_score,
            freshness      = f_score,
            sentiment_score = s_score,
            final_score    = final,
        ))

    # 기자 reporter_score도 최신화
    if news.reporter:
        news.reporter.reporter_score = int(r_score)

    return final


def run_reliability_update():
    """전체 뉴스에 대해 신뢰도 계산 및 저장"""
    db = SessionLocal()
    try:
        news_list = db.query(News).all()
        print(f"총 {len(news_list)}건 신뢰도 계산 시작...")
        for news in news_list:
            compute_and_save(news, db)
        db.commit()
        print("신뢰도 계산 완료!")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
    finally:
        db.close()


# ── 오케스트레이터 연동용 공개 API ────────────────────────────────────────────

def _grade(score: float) -> str:
    if score >= 70:
        return "HIGH"
    elif score >= 40:
        return "MEDIUM"
    else:
        return "LOW"


def get_reliability_result(news_id: int) -> dict:
    """
    단일 기사의 신뢰도를 계산해 dict로 반환하고 ReliabilityLog에 저장.

    Returns:
        {
            "news_id", "title", "url", "summary",
            "press_score", "reporter_score", "freshness_score", "sentiment_score",
            "final_score", "grade", "warnings"
        }
    """
    db = SessionLocal()
    try:
        news = db.query(News).filter(News.id == news_id).first()
        if not news:
            raise ValueError(f"news_id={news_id} 를 DB에서 찾을 수 없습니다.")

        p_score = calc_press_score(news.press)
        r_score = calc_reporter_score(news.reporter, news.press)
        f_score = calc_freshness(news.pub_date)
        s_score = calc_sentiment_neutrality(news.sentiment_score)
        final   = calc_final_score(p_score, r_score, f_score, s_score)

        # 경고 수집
        warnings = []
        if news.reporter and (news.reporter.correction_count or 0) > 0:
            warnings.append(f"정정 이력 {news.reporter.correction_count}건")
        if news.reporter and not news.reporter.email:
            warnings.append("공식 연락처 미확인")
        if not news.press:
            warnings.append("언론사 정보 없음")

        # ReliabilityLog 저장
        compute_and_save(news, db)
        db.commit()

        return {
            "news_id":        news_id,
            "title":          news.title,
            "url":            news.url,
            "summary":        news.summary or news.description or "",
            "press_score":    round(p_score, 2),
            "reporter_score": round(r_score, 2),
            "freshness_score": round(f_score, 2),
            "sentiment_score": round(s_score, 2),
            "final_score":    round(final, 2),
            "grade":          _grade(final),
            "warnings":       warnings,
        }
    finally:
        db.close()


def get_reliable_news(keyword: str, threshold: float = 60.0, top_n: int = 5) -> dict:
    """
    키워드로 기사를 검색해 신뢰도를 계산하고 threshold 이상인 기사만 반환.
    오케스트레이터 에이전트가 호출하는 메인 인터페이스.

    Returns:
        {
            "keyword": str,
            "threshold": float,
            "total_found": int,
            "passed": int,
            "articles": [ get_reliability_result() 형태 ... ]
        }
    """
    db = SessionLocal()
    try:
        query_str = f"%{keyword.replace(' ', '%')}%"
        news_list = db.query(News).filter(
            (News.title.like(query_str)) | (News.description.like(query_str))
        ).order_by(News.id.desc()).limit(30).all()
        news_ids = [n.id for n in news_list]
    finally:
        db.close()

    results = []
    for nid in news_ids:
        result = get_reliability_result(nid)
        if result["final_score"] >= threshold:
            results.append(result)

    results.sort(key=lambda x: x["final_score"], reverse=True)
    results = results[:top_n]

    return {
        "keyword":     keyword,
        "threshold":   threshold,
        "total_found": len(news_ids),
        "passed":      len(results),
        "articles":    results,
    }


def build_integration_payload(keyword: str, threshold: float = 60.0, top_n: int = 5) -> dict:
    """
    Integration Agent(오케스트레이터)에 넘기는 최종 payload.
    Market Agent의 integration_payload 포맷과 동일하게 맞춤.

    Args:
        keyword: 이벤트 키워드
        threshold: 신뢰도 최소 기준 (기본 60)
        top_n: 참고할 최대 기사 수

    Returns:
        {
            "agent_name": "News Agent",
            "signal": "Positive | Neutral | Cautious",
            "confidence": "High | Medium | Low",
            "score": float (-1.0 ~ 1.0),
            "news_reliability": "HIGH | MEDIUM | LOW",
            "key_evidence": [...],
            "key_risks": [...],
            "limitations": [...],
            "handoff_message": str
        }
    """
    news_result = get_reliable_news(keyword=keyword, threshold=threshold, top_n=top_n)
    articles = news_result["articles"]

    # 기사 없으면 신뢰 불가 판단
    if not articles:
        return {
            "agent_name": "News Agent",
            "signal": "Neutral",
            "confidence": "Low",
            "score": 0.0,
            "news_reliability": "LOW",
            "key_evidence": [],
            "key_risks": [],
            "limitations": [f"'{keyword}' 관련 신뢰도 {threshold}점 이상 기사 없음"],
            "handoff_message": f"'{keyword}' 관련 신뢰할 만한 뉴스가 없어 판단 근거를 제공할 수 없습니다."
        }

    # 평균 신뢰도
    avg_score = sum(a["final_score"] for a in articles) / len(articles)

    # 평균 감성 점수(0~100) → -1.0~1.0 변환
    # sentiment_score는 KoBERT 중립성 점수(높을수록 중립)이므로
    # 긍/부정 신호는 final_score + grade로 proxy
    # score = (avg_score - 50) / 50  → -1.0~1.0
    score = round((avg_score - 50) / 50, 3)
    score = max(-1.0, min(1.0, score))

    # signal
    if score >= 0.2:
        signal = "Positive"
    elif score <= -0.2:
        signal = "Cautious"
    else:
        signal = "Neutral"

    # confidence: 통과 기사 수 + 평균 신뢰도 기반
    passed = news_result["passed"]
    if passed >= 3 and avg_score >= 70:
        confidence = "High"
    elif passed >= 1 and avg_score >= 55:
        confidence = "Medium"
    else:
        confidence = "Low"

    # news_reliability
    if avg_score >= 70:
        news_reliability = "HIGH"
    elif avg_score >= 40:
        news_reliability = "MEDIUM"
    else:
        news_reliability = "LOW"

    # key_evidence: 신뢰도 높은 기사 요약
    key_evidence = [
        f"[{a['final_score']}점] {a['title']} — {a['summary'][:60]}..."
        if len(a['summary']) > 60 else f"[{a['final_score']}점] {a['title']} — {a['summary']}"
        for a in articles
    ]

    # key_risks: 각 기사의 warnings 수집
    key_risks = []
    for a in articles:
        for w in a.get("warnings", []):
            entry = f"{a['title'][:30]}... : {w}"
            if entry not in key_risks:
                key_risks.append(entry)

    # limitations
    limitations = []
    total_found = news_result["total_found"]
    if total_found > 0 and passed < total_found:
        limitations.append(f"전체 {total_found}건 중 {passed}건만 신뢰도 기준 통과")
    if passed < 3:
        limitations.append("신뢰도 기준 통과 기사가 적어 판단 근거가 제한적")

    handoff_message = (
        f"'{keyword}' 관련 뉴스 {passed}건 분석 완료. "
        f"평균 신뢰도 {avg_score:.1f}점({news_reliability}). "
        f"종합 신호: {signal}({confidence}). "
        f"핵심 기사: {articles[0]['title'][:40]}..."
        if articles else ""
    )

    return {
        "agent_name": "News Agent",
        "signal": signal,
        "confidence": confidence,
        "score": score,
        "news_reliability": news_reliability,
        "key_evidence": key_evidence,
        "key_risks": key_risks,
        "limitations": limitations,
        "handoff_message": handoff_message,
    }


if __name__ == "__main__":
    run_reliability_update()
