# 반도체 전문가 에이전트 — 작업 완료 보고서

> 작성일: 2026-05-09

---

## 1. 전체 아키텍처 요약

```
[데이터 수집] → [Postgres/Qdrant/Neo4j 저장] → [RAG 파이프라인] → [에이전트 파이프라인] → [리포트]
```

### 레이어별 구성

| 레이어 | 구성 파일 | 역할 |
|--------|-----------|------|
| **데이터 수집** | `collectors/` (8개) | 논문·특허·뉴스·주가·DART 수집 |
| **DB 저장** | `db/postgres.py`, `db/qdrant.py`, `db/neo4j_db.py` | TimescaleDB + Qdrant Cloud + Neo4j |
| **RAG** | `rag/embedder.py`, `rag/indexer.py`, `rag/retriever.py` | BGE-M3 하이브리드 검색 |
| **에이전트** | `agent/` (5개) | 5단계 파이프라인 + LLM 분석 |
| **스케줄러** | `jobs.py` | APScheduler 23개 크론 |

---

## 2. 에이전트 파이프라인 — 5단계 흐름

```
TechEvent 입력
      │
      ▼
① context_collect()   ← RAG 하이브리드 검색 (BGE-M3 + Qdrant)
      │  관련 선행 연구·특허·뉴스 최대 12청크
      ▼
② tech_evaluate()     ← LLM (claude-sonnet-4-6)
      │  혁신성(1~5) / TRL(1~9) / 재현가능성 / 선행기술 존재 여부
      ▼
③ competitive_map()   ← LLM
      │  수혜기업 / 위협기업 / 장비·소재 간접 영향
      ▼
④ calc_expected_value() ← LLM
      │  P(실현) × P(수혜) × 임팩트 = ev_score
      ▼
⑤ market_check()     ← Postgres (price_daily 테이블)
      │  최근 5일 주가 변화 → 기댓값 반영 여부 판단
      ▼
build_report()        → IntelligenceReport (마크다운 + 헤드라인)
```

---

## 3. 코드 리뷰에서 발견·수정한 버그 목록

### Bug 1 — `retriever.py`: `search()` API 호환성 완전 제거
- **문제**: qdrant-client v2.x에서 `client.search()` 메서드 삭제됨
- **과거 시도**: `hasattr()`, `__version__` 파싱, `importlib.metadata` 등 모두 실패
- **최종 수정**: 버전 감지 로직 전체 제거 → `client.query_points()` 단독 사용
- **파일**: `app/rag/retriever.py`

### Bug 2 — `llm.py`: 모델명 오류
- **문제**: `claude-opus-4-5` (존재하지 않는 모델)
- **수정**: `claude-sonnet-4-6` (올바른 모델 스트링)
- **파일**: `app/agent/llm.py`, `.env`

### Bug 3 — `steps.py`: SQL 윈도우 함수 중복 행 버그
- **문제**: `FIRST_VALUE() OVER (PARTITION BY ...)` 윈도우 함수가 입력 행 수만큼 반복 → 평균 계산 오류
- **수정**: `DISTINCT ON (company_code)` 서브쿼리 방식으로 변경 (최신 종가 / 5일 전 종가 정확히 1행씩)
- **파일**: `app/agent/steps.py`

### Bug 4 — `steps.py`: 미사용 임포트 2개
- **문제**: `from app.agent.models import IntelligenceReport` (steps.py에서 불필요)
- **문제**: `from app.rag.retriever import get_context_for_llm` (pipeline.py에서 직접 안 씀)
- **수정**: 두 줄 삭제
- **파일**: `app/agent/steps.py`

### Bug 5 — `indexer.py`: 미사용 `import json`
- **문제**: 파일 어디에도 json을 사용하지 않는데 임포트
- **수정**: 삭제
- **파일**: `app/rag/indexer.py`

### Bug 6 — Colab 파일 쓰기 셀: f-string 따옴표 충돌
- **문제**: Python 문자열 내 f-string에서 같은 따옴표 사용 → `SyntaxError: unterminated f-string`
- **수정**: f-string 외부에서 변수로 먼저 추출 (`src = r.get('source', '')`)
- **파일**: Colab 셀 (로컬 파일 영향 없음)

### Bug 7 — `market_check()`: 한국 코드만 주가 조회
- **문제**: `kr_codes = [c for c in codes if c.isdigit()]` → NVDA, TSMC 등 해외 종목 제외
- **현황**: 현재 `price_daily` 테이블에는 KRX 데이터만 있으므로 당장은 문제 없음
- **TODO**: 해외 종목 추가 시 yfinance 등 연동 필요

---

## 4. 신규 생성 파일

| 파일 | 설명 |
|------|------|
| `app/agent/__init__.py` | 패키지 초기화 |
| `app/agent/models.py` | 파이프라인 전체 공유 데이터클래스 7종 |
| `app/agent/llm.py` | Claude API 래퍼 (`call_llm`, `call_llm_json`) |
| `app/agent/steps.py` | 5단계 파이프라인 함수 구현 |
| `app/agent/reporter.py` | 마크다운 리포트 렌더러 |
| `app/agent/pipeline.py` | `run()` / `run_from_rag()` 진입점 |
| `run_agent_demo.py` | 데모 실행 스크립트 |
| `run_reindex.py` | BGE-M3 전체 재인덱싱 부트스트랩 |
| `run_search_demo.py` | 하이브리드 검색 6종 테스트 |
| `colab_semiconductor.ipynb` | Colab GPU 인덱싱 + 검색 테스트 노트북 |

---

## 5. 현재 데이터 현황

| 소스 | 데이터 종류 | 비고 |
|------|------------|------|
| arXiv | 반도체 논문 청크 (HBM, EUV, GAA 위주) | 2023~2025, BGE-M3 인덱싱 완료 |
| Semantic Scholar | 학술 논문 메타 | API 키 승인 대기 중 |
| KIPRIS | 한국 특허 | API 서비스 신청 필요 |
| RSS 뉴스 | 반도체 업계 뉴스 | 수집 중 |
| DART | 삼성·SK하이닉스·한미반도체 공시 | 수집 중 |
| price_daily | KRX 주가 (005930, 000660, 042700) | TimescaleDB |
| Qdrant | `semi_knowledge` 컬렉션 | dense 1024d + sparse 인덱싱 완료 |

---

## 6. TODO List (우선순위 순)

### 🔴 즉시 필요 (에이전트 실행 불가)

- [ ] **ANTHROPIC_API_KEY 입력**
  - `.env` 파일의 `ANTHROPIC_API_KEY=` 뒤에 본인 API 키 입력
  - 키 발급: https://console.anthropic.com

### 🟠 데이터 파이프라인 완성 (이번 주)

- [ ] **KIPRIS API 서비스 신청**
  - 주소: https://plus.kipris.or.kr → 마이페이지 → API 서비스 신청
  - 신청 항목: **특허·실용 공개·등록공보**
  - API 키는 `.env`에 이미 입력됨 (`KIPRIS_API_KEY`)

- [ ] **Semantic Scholar API 키 이메일 확인**
  - 승인 이메일 오면 `.env`의 `SEMANTIC_SCHOLAR_API_KEY=` 뒤에 입력

- [ ] **Google Drive → Colab 파일 동기화**
  - 로컬 `app/rag/retriever.py`를 Drive에 올려서 Colab이 최신 버전 쓰도록 업데이트
  - 핵심: `query_points()` 사용 버전이 Drive에 있어야 함

- [ ] **전체 재인덱싱 실행**
  ```bash
  # Colab 또는 로컬에서
  python run_reindex.py
  ```

### 🟡 품질 개선 (다음 주)

- [ ] **도메인 태깅 강화**
  - 많은 논문이 `general` 도메인으로 분류됨
  - `indexer.py`의 `_TAG_TO_DOMAIN` 딕셔너리 확장 필요
  - 추가 검토 태그: `cxl`, `hbm3`, `hbm4`, `gate_all_around`, `cfet`, `backside_power`

- [ ] **3D NAND 데이터 보강**
  - 현재 NAND 관련 청크가 거의 없음
  - `paper_collector.py`의 arXiv 쿼리에 NAND 키워드 추가:
    `3D NAND flash memory stacked layer CTF`

- [ ] **해외 종목 주가 연동 (선택)**
  - NVDA, TSMC, ASML 등이 수혜 기업으로 나올 때 `market_check()`가 작동 안 함
  - `yfinance` 또는 별도 API 연동 필요

### 🟢 운영 안정화 (이후)

- [ ] **에이전트 결과를 Postgres에 저장**
  - `intelligence_reports` 테이블 설계 → 히스토리 추적

- [ ] **차트 분석 에이전트 연결**
  - `market.signal == "buy_signal"` 시 차트 분석 에이전트로 TechEvent 전달하는 인터페이스

- [ ] **스케줄러 연동**
  - `jobs.py`에 새 논문 자동 감지 → 에이전트 파이프라인 자동 실행 크론 추가

---

## 7. 실행 방법 (준비 완료 후)

```bash
# 1. 환경 설정
pip install -r requirements.txt
# .env에 ANTHROPIC_API_KEY 입력

# 2. 스키마 초기화 (최초 1회)
python -m app.bootstrap_schema

# 3. 인덱싱 (Colab GPU 권장)
python run_reindex.py

# 4. 에이전트 실행 — 직접 이벤트 입력
python run_agent_demo.py

# 5. 에이전트 실행 — RAG 자동 탐지
python run_agent_demo.py "HBM4 hybrid bonding latest paper"
```

---

## 8. 검색 품질 현황

Colab 테스트 결과 (RRF 스코어 기준):

| 쿼리 | 상위 결과 RRF 스코어 | 평가 |
|------|---------------------|------|
| HBM bandwidth density | 0.031 | ✅ 양호 |
| EUV lithography stochastic defects | 0.028 | ✅ 양호 |
| Cu-Cu hybrid bonding pitch | 0.025 | ✅ 양호 |
| 3D NAND layer stacking | 0.012 | ⚠ 데이터 부족 |

> RRF 스코어는 절댓값보다 **순위 신호**로 해석. 0.02 이상이면 관련 문서가 충분히 존재하는 상태.

---

*보고서 끝 — 질문 있으면 편하게 물어봐 재용*
