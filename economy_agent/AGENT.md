# Macro Analysis Agent — 설계 문서

반도체 도메인 거시경제·지정학 리스크를 분석하는 LangGraph 기반 멀티에이전트 시스템입니다.

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [전체 아키텍처](#2-전체-아키텍처)
3. [데이터 수집 파이프라인](#3-데이터-수집-파이프라인)
4. [에이전트 실행 흐름](#4-에이전트-실행-흐름)
5. [컴포넌트 상세](#5-컴포넌트-상세)
6. [프롬프트 구조](#6-프롬프트-구조)
7. [DB 레이어](#7-db-레이어)
8. [출력 스키마](#8-출력-스키마)
9. [환경변수 및 의존성](#9-환경변수-및-의존성)
10. [실행 방법](#10-실행-방법)

---

## 1. 시스템 개요

### 역할

한국 반도체 수출 기업의 관점에서 다음 두 가지를 동시에 분석합니다.

- **거시경제 리스크**: 환율(원/달러), 금리(연방기금금리), 반도체지수(SOX), 생산·출하·재고지수
- **지정학 리스크**: 미-중 수출통제, 관세·무역보복, 대만해협 위기, 공급망 재편

### 설계 원칙

| 원칙 | 구현 방식 |
|------|-----------|
| 단일 책임 | 각 노드·도구는 하나의 역할만 수행 |
| 장애 격리 | DB 조회 실패 시에도 LLM 분석 계속 진행 (graceful degradation) |
| 중복 방지 | TimescaleDB: ON CONFLICT Upsert / Vector DB: SHA-256 청크 ID |
| 교체 가능성 | `ReportStoreProtocol`로 Vector DB 구현체 런타임 교체 가능 |
| 결정론적 출력 | LLM `temperature=0`, JsonOutputParser + 3단계 폴백 파싱 |

---

## 2. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                     외부 데이터 소스                              │
│  ECOS API    FRED API    yfinance    Google News RSS    KCIF PDF │
└──────┬──────────┬───────────┬───────────┬──────────────┬────────┘
       │          │           │           │              │
       ▼          ▼           ▼           ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│               데이터 수집 파이프라인  (run.py / pipeline.py)      │
│  Step 1: ECOS → TimescaleDB                                     │
│  Step 2: FRED+yfinance → TimescaleDB                            │
│  Step 3: Google News RSS → Vector DB (ChromaDB)                 │
│  Step 4: KCIF PDF 크롤링 → Vector DB (ChromaDB)                 │
└──────────────────────────────────────────────────────────────────┘
                    │                       │
                    ▼                       ▼
         ┌──────────────────┐   ┌───────────────────────┐
         │   TimescaleDB    │   │      ChromaDB          │
         │  macro_metrics   │   │   macro_context 컬렉션  │
         │  (시계열 지표)    │   │  (뉴스·리포트 청크)    │
         └────────┬─────────┘   └───────────┬───────────┘
                  │                         │
                  └──────────┬──────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MacroAnalysisAgent                             │
│                                                                  │
│   LangGraph StateGraph                                           │
│   START → [macro_analyst_node] → END                            │
│                                                                  │
│   macro_analyst_node 실행 흐름:                                  │
│     Step 1. Vector DB RAG 조회 (질문과 관련된 뉴스·리포트 5건)   │
│     Step 2. TimescaleDB 스냅샷 조회 (모든 지표 최신값)           │
│     Step 3. 컨텍스트 조합 (ECOS 섹션 / FRED 섹션 / 뉴스 섹션)   │
│     Step 4. gpt-4o 호출 (시스템 프롬프트 + 데이터 컨텍스트)      │
│     Step 5. JSON 파싱 (JsonOutputParser → 정규식 폴백 3단계)     │
└───────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
                    분석 결과 JSON dict
```

---

## 3. 데이터 수집 파이프라인

`run_ingestion_pipeline()` (`src/macro_agent/db/pipeline.py`)

### 실행 순서

```
Step 1  ECOS API  ──→  normalize_ecos_to_records()  ──→  insert_macro_data()  ──→  TimescaleDB
Step 2  FRED API  ──→  normalize_fred_to_records()  ──→  insert_macro_data()  ──→  TimescaleDB
        yfinance  ──┘
Step 3  Google News RSS ──→  _ingest_news_articles()  ──→  ingest_text_to_vector_db()  ──→  ChromaDB
Step 4  KCIF PDF 크롤링 ──→  extract_text_from_pdf()  ──→  ingest_text_to_vector_db()  ──→  ChromaDB
```

각 Step은 독립적으로 예외 처리됩니다. 한 Step이 실패해도 나머지 Step은 계속 실행됩니다.

### KCIF 크롤링 상세 흐름

```
1. GET /annual/reportList?pg={n}&pp=20
        └── rpt_no 목록 수집 (최대 30페이지)

2. GET /annual/reportView?rpt_no={n}
        ├── 날짜 추출: 정규식 YYYY.MM.DD
        └── fno 추출: 정규식 reportdownload('...')

3. POST /comm/AuthCheck
        └── auth_yn 확인 ("Y" = 공개 접근 허용)

4. GET /common/file/userDownload?atch_no={fno}
        └── PDF 바이트 수신
             └── PyMuPDF(fitz) 텍스트 추출
                  └── ingest_text_to_vector_db()
```

**중복 방지**: `data/ingested_report_urls.json` URL 캐시로 이미 적재된 리포트를 스킵합니다.

### TimescaleDB 저장 지표

| metric_name | 설명 | 단위 | 출처 |
|-------------|------|------|------|
| `ecos.usd_krw` | 원/달러 월평균 환율 | KRW/USD | ECOS 731Y004 |
| `ecos.electronics_shipment_index` | 전자부품 제조업 출하지수 | INDEX | ECOS 901Y032 |
| `ecos.electronics_inventory_index` | 전자부품 제조업 재고지수 | INDEX | ECOS 901Y032 |
| `market.sox_close` | 필라델피아 반도체지수 월봉 종가 | USD | yfinance ^SOX |
| `fred.manufacturing_ip` | 제조업 산업생산지수 | INDEX | FRED IPMAN |
| `fred.fed_funds_rate` | 연방기금 실효금리 | % | FRED FEDFUNDS |

---

## 4. 에이전트 실행 흐름

### AgentState (LangGraph 공유 상태)

```python
class AgentState(TypedDict, total=False):
    # 입력
    question: str          # 분석 요청 자연어 질문 (필수)
    sender:   str          # 질문 발신자 ("orchestrator", "user" 등)

    # 중간 산출물
    rag_context: str       # Vector DB 조회 결과 요약
    ts_context:  str       # TimescaleDB 조회 결과 요약

    # 출력
    analysis_result: dict  # 파싱된 JSON 분석 결과
    run_at:          str   # 완료 시각 (ISO8601 UTC)

    # 오류
    error:    str | None   # 치명적 오류 (None이면 정상)
    warnings: list[str]    # 비치명적 경고 (DB 연결 실패 등)
```

### macro_analyst_node 단계별 동작

```
입력: state["question"]
      ↓
[Step 1] query_vector_db(question, n_results=5)
          ChromaDB에서 코사인 유사도 기반 관련 문서 5건 검색
          실패 시 → warnings에 기록, 빈 리스트로 계속 진행
          ↓
[Step 2] query_latest_snapshot()
          TimescaleDB에서 모든 지표의 최신값 스냅샷 조회
          실패 시 → warnings에 기록, 빈 dict로 계속 진행
          ↓
[Step 3] build_context_string()
          ecos_data   ← prefix "ecos.*" 지표 JSON
          fred_data   ← prefix "fred.*" + "market.*" 지표 JSON
          news_context ← RAG 문서 포맷 문자열
          ↓
[Step 4] build_macro_chain(llm).invoke(chain_input)
          gpt-4o, temperature=0, max_tokens=4096
          실패 시 → tenacity 최대 3회 재시도 (지수 백오프 2–20초)
          ↓
[Step 5] _safe_parse_json(raw_output)
          1차: isinstance(raw, dict) → 통과
          2차: json.loads(raw_str)
          3차: 정규식으로 ```json ... ``` 블록 추출
          폴백: _parse_error=True 스키마 반환
          ↓
출력: state["analysis_result"] (분석 결과 dict)
```

---

## 5. 컴포넌트 상세

### MacroAnalysisAgent (`src/macro_agent/agent.py`)

오케스트레이터가 사용하는 퍼블릭 인터페이스. 내부 구현을 완전히 캡슐화합니다.

```python
agent = MacroAnalysisAgent(auto_init_db=False)

# 동기 호출
result: dict = agent.invoke("미중 수출통제 영향은?")

# 비동기 호출 (FastAPI, async 오케스트레이터)
result: dict = await agent.ainvoke("미중 수출통제 영향은?")

# 도메인 외 질문 감지
if not result.get("is_my_domain"):
    print(result["domain_rejection_reason"])
```

**보장**: `invoke()` / `ainvoke()`는 어떤 경우에도 예외를 전파하지 않고 항상 `dict`를 반환합니다.

### LangGraph 그래프 (`src/macro_agent/graph.py`)

현재 단일 노드 구조입니다.

```
START ──→ [macro_analyst] ──→ END
```

**확장 예시** (다중 노드 연결):
```python
builder.add_node("data_collector", data_collector_node)
builder.add_node("geo_analyst", geo_analyst_node)
builder.add_edge(START, "data_collector")
builder.add_edge("data_collector", "geo_analyst")
builder.add_edge("data_collector", "macro_analyst")
```

### 도구 목록

| 파일 | 함수/클래스 | 역할 |
|------|-------------|------|
| `tools/ecos_tool.py` | `fetch_ecos_data(months_back)` | ECOS API 환율·생산·출하·재고 수집 |
| `tools/fred_tool.py` | `fetch_fred_data(months_back)` | FRED+yfinance SOX·PMI·금리 수집 |
| `tools/news_tool.py` | `scraped_news_and_reports(...)` | Google News RSS + ChromaDB RAG 검색 |
| `tools/news_tool.py` | `upload_report_to_rag(content, ...)` | 리포트 수동 업로드 |
| `tools/fx_report_crawler.py` | `KCIFCrawler` | KCIF 리포트 PDF 자동 크롤링 |
| `tools/fx_report_crawler.py` | `crawl_and_ingest_fx_reports(months_back)` | 크롤링 → Vector DB 적재 통합 |

---

## 6. 프롬프트 구조

### 시스템 프롬프트 (`src/macro_agent/prompts/macro_agent.md`)

LLM에게 반도체 도메인 거시경제·지정학 분석 전문가 역할을 부여합니다. 파일로 관리되며 런타임에 로드됩니다.

### Human 메시지 템플릿 (`src/macro_agent/prompts/macro_prompt.py`)

```
현재 날짜: {current_date}

[섹션 A] 수집된 경제 데이터 (정량)
  A-1. ECOS 한국은행 지표       ← {ecos_data}  (TimescaleDB 스냅샷 JSON)
  A-2. FRED / yfinance 지표    ← {fred_data}  (TimescaleDB 스냅샷 JSON)

[섹션 B] 뉴스·리포트 컨텍스트 (정성)
  {news_context}               ← Vector DB RAG 검색 결과 (최대 5건)

[섹션 C] 분석 요청
  {query}                      ← 사용자 질문
```

### 지정학 전용 프롬프트 (`src/macro_agent/prompts/geo_prompt.py`)

`geo_analyst` 노드 확장 시 사용하는 서브 프롬프트입니다. 현재는 독립 노드로 미연결 상태이나 `build_geo_chain(llm)`으로 즉시 사용 가능합니다.

- **입력**: `news_context`, `current_date`, `focus_regions`
- **위험 분류**: EXPORT_CONTROL, TARIFF_TRADE, ALLIANCE_SHIFT, SUPPLY_DISRUPTION, SANCTIONS, REGULATORY_CHANGE
- **출력**: `geo_risk_summary`, `overall_geo_risk`, `risk_events[]`, `watchlist[]`

---

## 7. DB 레이어

### TimescaleDB (`src/macro_agent/db/timescale/`)

PostgreSQL 기반 시계열 DB로 정량 지표를 저장합니다.

**테이블: `macro_metrics`**

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `time` | TIMESTAMPTZ | UTC 타임스탬프 (파티션 키) |
| `metric_name` | TEXT | 지표 코드 (예: `ecos.usd_krw`) |
| `value` | DOUBLE PRECISION | 수치값 |
| `source` | TEXT | `ecos` / `fred` / `market` |
| `region` | TEXT | `KR` / `US` |
| `unit` | TEXT | 단위 (예: `KRW/USD`, `%`) |
| `metadata` | JSONB | 추가 속성 (SOX OHLCV 등) |

**고유 제약**: `(time, metric_name, source)` — 동일 값이면 WAL 기록 없이 스킵

### ChromaDB (`src/macro_agent/db/vector/`)

뉴스·리포트의 의미론적 검색을 위한 Vector DB입니다.

- **컬렉션**: `macro_context`
- **임베딩**: OpenAI text-embedding (LangChain 기본)
- **청킹**: `chunk_size=800, chunk_overlap=120` (한국어 금융 리포트 기준)
- **중복 방지**: `SHA-256(content + source_name + published_date)[:32]` 청크 ID

**환경변수로 영속/임시 전환**:
```
CHROMA_PERSIST_DIR=./data/chroma_db  # 영속 (기본)
CHROMA_PERSIST_DIR=                  # 미설정 시 인메모리 (세션 휘발)
```

### ReportStoreProtocol (의존성 주입)

`news_tool.py`의 RAG 검색은 `ReportStoreProtocol`을 통해 추상화되어 있습니다.

```python
# 초기화 시 ChromaDB로 교체
from macro_agent.db.vector.repository import ChromaReportStore
from macro_agent.tools.news_tool import set_report_store

set_report_store(ChromaReportStore())   # MacroAnalysisAgent.__init__에서 자동 수행
```

---

## 8. 출력 스키마

`agent.invoke()`는 항상 다음 구조의 `dict`를 반환합니다.

```jsonc
{
  "schema_version": "1.0",
  "is_my_domain": true,            // false이면 domain_rejection_reason 참조
  "domain_rejection_reason": null, // 도메인 외 질문 거부 사유
  "query": "분석 요청 원문",
  "analysis_timestamp": "2026-05-20T10:00:00Z",

  "reasoning_flow": "원인 → 1차 영향 → 2차 영향 → 최종 반도체 영향",

  "macro_analysis": {
    "exchange_rate":   { "current": ..., "trend": ..., "risk_level": "...", "impact": "..." },
    "interest_rate":   { "current": ..., "trend": ..., "risk_level": "...", "impact": "..." },
    "sox_index":       { "current": ..., "trend": ..., "risk_level": "...", "impact": "..." },
    "semiconductor_cycle": { "phase": "...", "risk_level": "...", "impact": "..." }
  },

  "geo_analysis": {
    "geo_risk_summary": "한 문장 요약",
    "overall_geo_risk": "LOW|MEDIUM|HIGH|CRITICAL",
    "risk_events": [
      {
        "event_id": "GEO-001",
        "category": "EXPORT_CONTROL",
        "region": "미-중",
        "event_description": "...",
        "key_actors": ["미국 BIS", "화웨이"],
        "regulation_reference": "BIS EAR § 744",
        "affected_semiconductor_segments": ["HBM", "AI 가속기"],
        "risk_level": "HIGH",
        "impact_horizon": "SHORT|MID|LONG",
        "korea_exposure_level": "HIGH",
        "reasoning_flow": "원인: ... → 1차 영향: ... → 2차 영향: ... → 최종 반도체 영향: ..."
      }
    ],
    "watchlist": ["모니터링 신호 1", "모니터링 신호 2"]
  },

  "overall_risk_level": "LOW|MEDIUM|HIGH|CRITICAL",
  "key_signals": ["핵심 신호 1", "핵심 신호 2"],
  "summary": "최종 종합 요약 (2–3문장)",
  "confidence_score": 0.85,         // 0.0–1.0
  "data_sources": ["ECOS", "FRED", "국제금융센터(KCIF)"],

  // 에이전트 실행 메타데이터
  "_agent_meta": {
    "run_at": "2026-05-20T10:00:05Z",
    "rag_context": "RAG 5건 사용",
    "ts_context": "TimescaleDB 6개 지표 사용",
    "sender": "user",
    "warnings": [],
    "fatal_error": null
  }
}
```

**오류 시 반환 필드**:
- `_parse_error: true` — LLM이 유효한 JSON을 출력하지 않은 경우
- `_agent_meta.fatal_error` — LLM 호출 자체가 실패한 경우

---

## 9. 환경변수 및 의존성

### 필수 환경변수 (`.env`)

```bash
OPENAI_API_KEY=sk-...          # gpt-4o 호출 및 ChromaDB 임베딩
ECOS_API_KEY=...               # 한국은행 ECOS API 인증키
FRED_API_KEY=...               # FRED API 인증키

DATABASE_URL=postgresql://user:pass@localhost:5432/macro_db  # TimescaleDB

CHROMA_PERSIST_DIR=./data/chroma_db  # ChromaDB 영속 경로
```

### 핵심 의존성

| 패키지 | 역할 |
|--------|------|
| `langgraph>=0.2` | StateGraph 오케스트레이션 |
| `langchain-openai>=0.3` | gpt-4o 호출 |
| `chromadb>=0.5` | Vector DB |
| `psycopg2-binary>=2.9` | TimescaleDB 드라이버 |
| `langchain-text-splitters>=0.3` | 텍스트 청킹 |
| `PyMuPDF>=1.24` | PDF 텍스트 추출 |
| `beautifulsoup4>=4.12` | KCIF HTML 파싱 |
| `yfinance>=0.2.40` | SOX 지수 수집 |
| `feedparser>=6.0` | Google News RSS 파싱 |
| `tenacity>=8.3` | API 호출 재시도 |

---

## 10. 실행 방법

```bash
# 의존성 설치
pip install -e .

# TimescaleDB 스키마 초기화 (최초 1회)
python -c "from macro_agent.db.timescale.client import initialize_schema; initialize_schema()"

# ── 데이터 수집 ────────────────────────────────────────────────────────

# 기본 수집 (6개월치 ECOS + FRED + 뉴스 + KCIF 리포트)
python run.py --ingest

# 장기 수집 (36개월치)
python run.py --ingest --months 36

# FX 리포트 제외
python run.py --ingest --no-fx-reports

# KCIF 리포트만 크롤링 (3개월)
python run.py --crawl-reports

# KCIF 리포트 12개월치
python run.py --crawl-reports --months 12

# ── 에이전트 질의 ──────────────────────────────────────────────────────

# 기본 질문
python run.py

# 커스텀 질문
python run.py "미중 반도체 수출통제가 HBM 공급망에 미치는 영향은?"

# ── Python API ──────────────────────────────────────────────────────────

from macro_agent.agent import MacroAnalysisAgent

agent = MacroAnalysisAgent(auto_init_db=False)
result = agent.invoke("현재 반도체 업황과 미중 지정학 리스크를 분석해줘.")
print(result["summary"])
print(result["overall_risk_level"])
```

---

## 파일 구조

```
macro-analysis-agent/
├── run.py                              # CLI 진입점
├── pyproject.toml                      # 의존성 정의
├── .env                                # 환경변수 (gitignore)
├── data/
│   ├── chroma_db/                      # ChromaDB 영속 저장소
│   └── ingested_report_urls.json       # KCIF URL 캐시 (중복 방지)
└── src/macro_agent/
    ├── agent.py                        # MacroAnalysisAgent (퍼블릭 인터페이스)
    ├── graph.py                        # LangGraph StateGraph 정의
    ├── state.py                        # AgentState TypedDict
    ├── nodes/
    │   └── macro_analyst.py            # 분석 노드 (5단계 실행 흐름)
    ├── prompts/
    │   ├── macro_agent.md              # 시스템 프롬프트 (LLM 역할 정의)
    │   ├── macro_prompt.py             # Human 메시지 템플릿 + 체인 빌더
    │   └── geo_prompt.py              # 지정학 전용 서브 프롬프트
    ├── tools/
    │   ├── ecos_tool.py               # ECOS API 수집 도구
    │   ├── fred_tool.py               # FRED + yfinance 수집 도구
    │   ├── news_tool.py               # Google News RSS + RAG 인터페이스
    │   └── fx_report_crawler.py       # KCIF PDF 크롤러
    └── db/
        ├── pipeline.py                # 통합 수집 파이프라인
        ├── timescale/
        │   ├── client.py              # PostgreSQL 연결 관리
        │   └── repository.py         # TimescaleDB CRUD + 정규화
        └── vector/
            ├── client.py             # ChromaDB 클라이언트
            └── repository.py        # 청킹·임베딩·저장·검색
```
