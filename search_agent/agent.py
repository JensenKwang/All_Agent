import os
import json
import re
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("GOOGLE_API_KEY"):
    raise EnvironmentError("GOOGLE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

from openai import OpenAI
from reliability import get_reliable_news

OUT_DIR = Path("./news_agent_data")
INTEGRATION_PAYLOAD_FILE = OUT_DIR / "news_agent_integration_payload.json"
LLM_JSON_FILE = OUT_DIR / "news_agent_llm_report.json"
FINAL_TXT_FILE = OUT_DIR / "news_agent_final_report.txt"


def ensure_output_dir():
    OUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# [1] NewsReporter (Rule-based)
# ============================================================

class NewsReporter:
    def analyze(self, keyword: str, threshold: float = 60.0, top_n: int = 5) -> dict:
        result = get_reliable_news(keyword, threshold=threshold, top_n=top_n)

        articles = result["articles"]
        passed = result["passed"]
        total = result["total_found"]

        if not articles:
            return {
                "keyword": keyword,
                "signal": "Neutral",
                "confidence": "Low",
                "avg_score": 0.0,
                "grade": "LOW",
                "key_evidence": [],
                "key_risks": [],
                "limitations": [f"신뢰도 기준({threshold}점) 통과 기사 없음. 전체 {total}건 중 0건 통과"],
                "articles": []
            }

        avg_score = sum(a["final_score"] for a in articles) / len(articles)

        positive = sum(1 for a in articles if a.get("sentiment_score", 50) > 60)
        negative = sum(1 for a in articles if a.get("sentiment_score", 50) < 40)

        if positive > negative and positive >= len(articles) * 0.5:
            signal = "Positive"
        elif negative > positive and negative >= len(articles) * 0.5:
            signal = "Negative"
        else:
            signal = "Neutral"

        if avg_score >= 70 and passed >= 3:
            confidence = "High"
        elif avg_score >= 55 or passed >= 2:
            confidence = "Medium"
        else:
            confidence = "Low"

        grade = "HIGH" if avg_score >= 70 else ("MEDIUM" if avg_score >= 50 else "LOW")

        key_evidence = [
            f"[{a['final_score']:.1f}점] {a['title']} — {a['summary'][:80]}..."
            for a in articles
        ]

        key_risks = []
        for a in articles:
            for w in a.get("warnings", []):
                key_risks.append(f"{a['title'][:30]}... : {w}")

        limitations = [f"전체 {total}건 중 {passed}건만 신뢰도 기준 통과"] if passed < total else []

        return {
            "keyword": keyword,
            "signal": signal,
            "confidence": confidence,
            "avg_score": round(avg_score, 2),
            "grade": grade,
            "key_evidence": key_evidence,
            "key_risks": key_risks,
            "limitations": limitations,
            "articles": articles
        }


# ============================================================
# [2] OpenAINewsInterpreter (LLM)
# ============================================================

class OpenAINewsInterpreter:
    def __init__(self, api_key=None, model="gpt-4.1-mini"):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model

    def _make_prompt(self, rule_based: dict) -> str:
        schema = {
            "agent": "News Agent",
            "decision_type": "llm_news_judgment",
            "integration_payload": {
                "agent_name": "News Agent",
                "signal": "Positive | Negative | Neutral | Cautious",
                "confidence": "High | Medium | Low",
                "score": "float between -1.0 and 1.0",
                "news_reliability": "HIGH | MEDIUM | LOW",
                "key_evidence": ["..."],
                "key_risks": ["..."],
                "limitations": ["..."],
                "handoff_message": "Integration Agent에 전달할 요약"
            }
        }

        return f"""
너는 Multi AI Agent 기반 반도체 주가 예측 시스템의 News Agent다.

[중요]
다른 Agent가 담당하는 영역은 판단하지 마라.
- 주가/시장 기술적 분석 금지
- 수급/거래량 분석 금지
- 산업 펀더멘털 분석 금지
- 최종 투자 추천 금지

[너의 역할]
수집된 뉴스 기사의 신뢰도와 감성을 판단하여 Integration Agent에 넘길 News Agent 관점의 독립 판단을 내려야 한다.

[판단 기준]
- 뉴스 신뢰도가 충분한가 (언론사, 기자, 최신성 기반)
- 기사 내용이 해당 종목에 긍정/부정적인가
- 신뢰도 낮은 기사가 많으면 Cautious를 고려하라
- 기사 수가 적거나 신뢰도 기준 통과 기사가 없으면 confidence를 Low로 하라

[입력 데이터 (rule-based 결과)]
{json.dumps(rule_based, ensure_ascii=False, indent=2)}

[출력 규칙]
반드시 JSON만 출력하라.
markdown code block을 쓰지 마라.
입력에 없는 외부 사실을 만들지 마라.
Buy/Sell/Hold 같은 최종 투자 의견을 내지 마라.

[출력 JSON schema]
{json.dumps(schema, ensure_ascii=False, indent=2)}

[score 기준]
- +1.0에 가까울수록 뉴스가 긍정적이고 신뢰도 높음
- 0에 가까울수록 중립 또는 혼재
- -1.0에 가까울수록 부정적이거나 신뢰도 낮음
"""

    def _parse_json(self, text: str) -> dict:
        try:
            return json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise ValueError("OpenAI 응답을 JSON으로 파싱하지 못했습니다.")

    def generate_llm_report(self, rule_based: dict) -> dict:
        prompt = self._make_prompt(rule_based)
        response = self.client.responses.create(
            model=self.model,
            input=prompt,
            temperature=0.2
        )
        text = response.output_text.strip()

        try:
            parsed = self._parse_json(text)
        except Exception as e:
            parsed = {"parse_error": str(e), "raw_text": text}

        return {
            "agent": "News Agent",
            "model": self.model,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "llm_judgment": parsed,
            "raw_text": text
        }


# ============================================================
# [3] NewsAgent
# ============================================================

class NewsAgent:
    def __init__(self, use_llm=True, openai_api_key=None, model="gpt-4.1-mini"):
        self.reporter = NewsReporter()
        self.use_llm = use_llm
        self.llm_interpreter = None

        if use_llm:
            self.llm_interpreter = OpenAINewsInterpreter(
                api_key=openai_api_key,
                model=model
            )

    def run(self, keyword: str, threshold: float = 60.0, top_n: int = 5) -> dict:
        ensure_output_dir()

        print(f"[START] News Agent Analysis - keyword: '{keyword}'")

        rule_based = self.reporter.analyze(keyword, threshold=threshold, top_n=top_n)

        llm_report = None
        integration_payload = None

        if self.use_llm and self.llm_interpreter:
            llm_report = self.llm_interpreter.generate_llm_report(rule_based)

            judgment = llm_report.get("llm_judgment", {})
            if "integration_payload" in judgment:
                integration_payload = judgment["integration_payload"]

        if integration_payload is None:
            integration_payload = self._build_fallback_payload(keyword, rule_based)

        slug = keyword.replace(" ", "_")
        payload_file = OUT_DIR / f"news_agent_integration_payload_{slug}.json"
        llm_file = OUT_DIR / f"news_agent_llm_report_{slug}.json"
        txt_file = OUT_DIR / f"news_agent_final_report_{slug}.txt"

        with open(payload_file, "w", encoding="utf-8") as f:
            json.dump(integration_payload, f, ensure_ascii=False, indent=2)

        if llm_report:
            with open(llm_file, "w", encoding="utf-8") as f:
                json.dump(llm_report, f, ensure_ascii=False, indent=2)

        self._build_txt_report(keyword, rule_based, integration_payload, txt_file)

        print("[DONE] News Agent Analysis")
        print(f"integration payload: {payload_file}")
        print(f"txt report        : {txt_file}")

        return {
            "rule_based": rule_based,
            "llm_report": llm_report,
            "integration_payload": integration_payload
        }

    def _build_txt_report(self, keyword: str, rule_based: dict, payload: dict, txt_file: Path = FINAL_TXT_FILE):
        lines = []
        lines.append("=" * 70)
        lines.append("News Agent Analysis Report")
        lines.append("=" * 70)
        lines.append(f"생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"분석 키워드: {keyword}")
        lines.append("")

        lines.append("[분석 요약]")
        lines.append(f"- Signal         : {payload.get('signal', 'N/A')}")
        lines.append(f"- Confidence     : {payload.get('confidence', 'N/A')}")
        lines.append(f"- Score          : {payload.get('score', 'N/A')}")
        lines.append(f"- News Reliability: {payload.get('news_reliability', 'N/A')}")
        lines.append(f"- 분석 기사 수    : 전체 {rule_based.get('articles', []).__len__()}건 중 {len([a for a in rule_based.get('articles', [])])}건 통과")
        lines.append("")

        if payload.get("key_evidence"):
            lines.append("[핵심 근거]")
            for e in payload["key_evidence"]:
                lines.append(f"- {e}")
            lines.append("")

        if payload.get("key_risks"):
            lines.append("[리스크]")
            for r in payload["key_risks"]:
                lines.append(f"- {r}")
            lines.append("")

        if payload.get("limitations"):
            lines.append("[해석 제한]")
            for lm in payload["limitations"]:
                lines.append(f"- {lm}")
            lines.append("")

        lines.append("[Integration Agent 전달 메시지]")
        lines.append(payload.get("handoff_message", ""))

        with open(txt_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _build_fallback_payload(self, keyword: str, rule_based: dict) -> dict:
        score = self._signal_to_score(rule_based["signal"], rule_based["avg_score"])
        return {
            "agent_name": "News Agent",
            "signal": rule_based["signal"],
            "confidence": rule_based["confidence"],
            "score": score,
            "news_reliability": rule_based["grade"],
            "key_evidence": rule_based["key_evidence"],
            "key_risks": rule_based["key_risks"],
            "limitations": rule_based["limitations"],
            "handoff_message": (
                f"'{keyword}' 관련 뉴스 분석 완료. "
                f"평균 신뢰도 {rule_based['avg_score']}점({rule_based['grade']}). "
                f"종합 신호: {rule_based['signal']}({rule_based['confidence']})."
            )
        }

    def _signal_to_score(self, signal: str, avg_score: float) -> float:
        base = round((avg_score - 50) / 50, 3)
        if signal == "Positive":
            return round(min(1.0, base + 0.3), 3)
        elif signal == "Negative":
            return round(max(-1.0, base - 0.3), 3)
        return base


# ============================================================
# [4] Integration Agent용 인터페이스
# ============================================================

def run_as_news_agent(keyword: str, use_llm: bool = True) -> dict:
    """Integration Agent에서 직접 호출하는 인터페이스."""
    agent = NewsAgent(use_llm=use_llm)
    result = agent.run(keyword)
    return result["integration_payload"]


# ============================================================
# [5] 실행
# ============================================================

if __name__ == "__main__":
    import sys

    keyword = sys.argv[1] if len(sys.argv) > 1 else "삼성전자 HBM"
    USE_LLM = True

    agent = NewsAgent(use_llm=USE_LLM)
    result = agent.run(keyword)

    print(json.dumps(result["integration_payload"], ensure_ascii=False, indent=2))
