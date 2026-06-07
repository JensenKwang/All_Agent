# 반도체 뉴스 멀티에이전트 시스템

반도체 관련 뉴스, 공시, SNS 데이터를 수집·분석하는 멀티에이전트 시스템입니다.

---

## 프로젝트 구조

```
graduate/
├── search_agent.py          # 데이터 수집 에이전트 (A2A 진입점)
├── naver_news_api.py        # 네이버 뉴스 API 수집 모듈
├── dart_api.py              # DART 전자공시 API 수집 모듈
├── database.py              # DB 세션 및 저장 함수
├── models.py                # SQLAlchemy DB 모델
├── report.py                # DB 통계 리포트
└── .env                     # API 키 설정 (아래 참고)
```

---

## 환경 설정

### 1. 패키지 설치

```bash
pip install -r requirements.txt
```

### 2. .env 파일 설정

프로젝트 루트에 `.env` 파일을 생성하고 아래 키를 입력합니다.

```env
DART_API_KEY=your_dart_api_key
NAVER_CLIENT_ID=your_naver_client_id
NAVER_CLIENT_SECRET=your_naver_client_secret
```

### 3. DB 초기화

```bash
python database.py
```

---

## search_agent 사용법

### 다른 에이전트에서 호출 (A2A 로컬 호출)

```python
from search_agent import run

result = run("삼성전자")

result["query"]          # 검색 키워드
result["news"]           # 네이버 뉴스 기사 리스트
result["disclosures"]    # DART 공시 리스트
```

수집 건수 조절:

```python
result = run("SK하이닉스", news_count=20, disclosure_count=50)
```

### 직접 실행 (단독 테스트)

```bash
python search_agent.py 삼성전자
python search_agent.py "SK하이닉스 HBM"
```

### 반환 데이터 구조

`run()`은 integration_payload 형식으로 반환합니다.

```json
{
  "agent_name": "Search Agent",
  "keyword": "삼성전자",
  "news_count": 10,
  "disclosure_count": 5,
  "threads_count": 2,
  "key_evidence": [
    "[뉴스] 삼성전자, HBM3E 양산 본격화 — 전자신문 (2026-06-06 09:00:00)",
    "[공시] 사업보고서 — 삼성전자 (20260606)",
    "[SNS] @influencer: HBM 관련 포스트 내용..."
  ],
  "limitations": [],
  "handoff_message": "'삼성전자' 관련 데이터 수집 완료. 뉴스 10건 / 공시 5건 / SNS 2건 (총 17건).",
  "raw": {
    "news": [...],
    "disclosures": [...],
    "threads_posts": [...]
  }
}
```

---

## 개별 모듈 직접 실행

```bash
# 네이버 뉴스 테스트
python naver_news_api.py

# DART 공시 테스트
python dart_api.py

# DB 통계 리포트
python report.py
```

