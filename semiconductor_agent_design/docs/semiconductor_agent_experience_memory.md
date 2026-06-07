# Semiconductor Agent Experience Memory

## 목적

반도체 에이전트의 백테스트 결과를 단순 가중치 조정에만 쓰지 않고, 다음 세 가지 경험 데이터로 재사용한다.

1. `Calibration`
- 예측 밴드, confidence, 축별 해석을 보정한다.

2. `Error Taxonomy`
- 왜 틀렸는지 패턴화한다.
- 예: `direction_flip`, `volatility_underweighted`, `missing_tech_event_context`

3. `Case Memory`
- 새 이벤트가 들어왔을 때 과거 유사 사례를 바로 조회한다.

## 데이터 층

### 1. Knowledge Layer
- `tech_documents`
- `tech_document_chunks`
- 논문, 공식자료, 기술 블로그, 뉴스

### 2. Event Layer
- `event_candidates`
- `event_outcomes`
- 문서를 가격 관련 기술 이벤트로 구조화한 층

### 3. Experience Layer
- `price_forecast_evaluations`
- `forecast_experience_cases`
- `forecast_experience_stats`
- 예측 실패/성공 패턴과 유사 사례 메모리 층

## 핵심 흐름

1. 과거 시점 `as_of` 기준으로 예측 생성
2. 실제값 도달 후 `price_forecast_evaluations` 저장
3. 평가 결과를 `forecast_experience_cases`로 변환
4. 케이스를 패턴/회사/도메인별 통계로 집계
5. 다음 이벤트 해석 시 과거 유사 사례와 성공률을 참조

## 경험 케이스 필드

- `success_label`
  - `success`, `partial`, `failure`
- `primary_pattern`
  - 해당 케이스의 대표 실패/성공 패턴
- `error_tags`
  - 세부 태그 목록
- `related_domain`
  - HBM, litho, packaging 등
- `event_signature`
  - 새 케이스와 유사성 비교용 요약 시그니처
- `context`
  - signals, features, scenarios, feedback
- `outcome`
  - realized return, abs error, interval hit

## 실패 유형 taxonomy v1

- `direction_flip`
- `already_priced_in_miss`
- `macro_override`
- `volatility_underweighted`
- `band_too_narrow`
- `missing_tech_event_context`
- `tech_signal_misread`
- `novelty_overestimated`
- `revenue_linkage_overestimated`
- `wrong_company_mapping`

## 어떻게 활용하나

### 해석 모듈 보정
- 특정 이벤트 타입이 반복적으로 실패하면 confidence를 낮춘다.
- 특정 도메인에서 밴드가 자주 좁으면 변동성 반영을 키운다.

### 유사 사례 검색
- 새 HBM 이벤트가 들어오면 과거 HBM/메모리/샘플출하 케이스를 조회한다.
- 과거 성공/실패 이유를 현재 해석 리포트에 반영한다.

### RAG 개선 신호
- 실패 원인이 `weak_semiconductor_evidence`이면, 공식자료/논문 검색이 부족했다는 뜻이다.
- 이 경우 RAG 검색 우선순위를 다시 조정한다.

## 현재 구현 상태

### 구현 완료
- `forecast_experience_cases`
- `forecast_experience_stats`
- 백테스트 평가 -> 경험 케이스 변환
- 패턴/회사/도메인 통계 집계
- 유사 사례 조회 helper

### 다음 단계
- 반도체 기술 이벤트 스키마와 직접 연결
- 경험 데이터를 반도체 에이전트 최종 프롬프트/리포트에 반영
- 회사별/도메인별 confidence calibration 자동화
