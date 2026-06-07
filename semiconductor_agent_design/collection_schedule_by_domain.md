# Semiconductor Expert Agent - Collection Schedule (Domain x Cadence)

기준 시간대: Asia/Seoul

## Daily
| Domain | Source | Job | Time/Frequency | Ingestion Target |
|---|---|---|---|---|
| Domain 1 공공/금융 | Open DART | 신규 공시 폴링 | 매 10분 (09:00-18:30) | Postgres(raw_events, disclosures) + Object Storage(XML) |
| Domain 1 공공/금융 | KRX | 일별 시세/수급 | 16:10 | Postgres(price_daily, investor_flow) |
| Domain 1 공공/금융 | ECOS | 환율/금리 | 11:00 | Postgres(macro_daily) |
| Domain 3 미디어/커뮤니티 | RSS 5종 | 기사 수집/파싱 | 매 30분 | Qdrant(news_chunks) + Postgres(news_signals) |
| Domain 4 학회/논문 | arXiv API | 신규 논문 수집 | 06:00 | Qdrant(paper_chunks) + Object Storage(pdf) |

## Weekly
| Domain | Source | Job | Time/Frequency | Ingestion Target |
|---|---|---|---|---|
| Domain 3 기술지식 동적 | 삼성/SK/마이크론/ASML/Lam/AMAT/KLA | 기술 블로그 수집 | 화/금 08:00 | Qdrant(tech_blog_chunks) |
| Domain 4 학회/논문 | Semantic Scholar | 인용 급증/주제 군집 갱신 | 수 07:00 | Postgres(paper_trend_features) |
| Domain 1 특허 | KIPRIS | 핵심 IPC 배치 | 월 07:00 | Postgres(patent_events, patent_metrics) |

## Monthly
| Domain | Source | Job | Time/Frequency | Ingestion Target |
|---|---|---|---|---|
| Domain 1 공공통계 | KOSIS | 생산/출하/재고 지수 수집 | 매월 15일 09:00 | Postgres(kosis_monthly) |
| Domain 1 무역통계 | 관세청 | HS코드 수출입/단가 프록시 | 매월 20일 09:00 | Postgres(customs_monthly, asp_proxy) |
| Domain 2 산업데이터 | WSTS | Blue Book 업데이트 | 매월 28일 09:00 | Postgres(wsts_monthly) |
| Domain 2 산업데이터 | SEMI/Gartner/IDC PR | 수치 추출 | 매월 1일 + 이벤트 트리거 | Postgres(industry_press_metrics) |
| Domain 5 표준지식 | JEDEC | 개정 여부 확인/동기화 | 매월 1일 07:00 | Qdrant(jedec_chunks) + Object Storage(pdf) |

## Yearly
| Domain | Source | Job | Time/Frequency | Ingestion Target |
|---|---|---|---|---|
| Domain 5 정적지식 | IEEE IRDS | 연간 신판 수집/재인덱싱 | 매년 11월 1일 09:00 | Qdrant(irds_chunks) + Object Storage(pdf) |
| Domain 4 학회자료 | Hot Chips/FMS 등 | 공개 슬라이드 일괄 수집 | 매년 8월 20일 09:00 | Qdrant(conference_chunks) + Object Storage(ppt/pdf) |

## Event-driven (상시)
| Trigger | Action |
|---|---|
| DART 중요 공시(B001/F001/C001) | 관련 기업 feature 재계산 + 앙상블 재평가 |
| RSS에서 고강도 키워드(HBM4/수율/다운타임) 탐지 | 뉴스 신뢰도 스코어링 후 즉시 알림 |
| 논문/표준 문서 신규 버전 탐지 | 도메인 지식 KB 증분 인덱싱 |

## Operational Rules
- 모든 레코드에 `published_at`, `observed_at`, `valid_from`, `valid_to` 저장 (look-ahead bias 방지)
- Tier 3~4 소스는 Tier 1~2 교차 검증 시에만 feature confidence 상향
- 실패 재시도 정책: 1분/5분/30분 exponential backoff, 3회 실패 시 알림
