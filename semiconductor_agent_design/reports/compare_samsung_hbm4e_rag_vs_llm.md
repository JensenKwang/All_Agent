# LLM vs RAG Comparison

- Topic: 2026년 5월 29일 삼성전자의 HBM4E 샘플 출하 발표는 삼성전자와 SK하이닉스의 7~30일 주가에 어떤 영향을 줄까?

## LLM Only
- Recommendation: `investable`
- Confidence: `0.00` / reasoning `0.00`
- Catalyst Imminence: `0-7d`
- Bottleneck Importance: `high`
- Novelty: `medium` / `partially_known`
- Revenue Linkage: `direct` -> `8-30d`
- Market Transmission Speed: `fast`
- Evidence Quality: `B`
- Thesis: The announcement of HBM4E samples is likely to positively impact Samsung and SK Hynix in the short to medium term, with significant implications for the semiconductor market.
- Company Impact: Samsung Electronics(005930):benefit@0.80, SK Hynix(000660):benefit@0.70

## RAG + LLM
- Recommendation: `investable`
- Confidence: `0.84` / reasoning `1.00`
- Catalyst Imminence: `0-7d`
- Bottleneck Importance: `high`
- Novelty: `high` / `new`
- Revenue Linkage: `direct` -> `0-7d`
- Market Transmission Speed: `fast`
- Evidence Quality: `A`
- Thesis: Samsung's HBM4E launch is a significant market catalyst, likely boosting its stock in the near term.
- Company Impact: Samsung Electronics(005930):benefit@0.90, SK Hynix(000660):neutral@0.70
- Evidence:
  - company_official/samsung_global_newsroom: Samsung Electronics Begins Shipment of Industry-First HBM4E Samples (score=1.000)
  - semi_blog/skhynix_newsroom: What Does P&T7 Mean for Cheongju? A New AI Memory Production Hub and Catalyst for the Local Economy (score=0.916)
  - company_official/samsung_global_newsroom: [Infographic] Samsung AI Appliances Deliver Inclusive Experiences Through Enhanced Accessibility Features (score=0.883)
  - paper/arxiv: Photonic Fabric Platform for AI Accelerators (score=0.866)
  - paper/arxiv: MemExplorer: Navigating the Heterogeneous Memory Design Space for Agentic Inference NPUs (score=0.850)

## What Changed
- Evidence quality: `B -> A`
- Evidence count: `0 -> 8`
- Source count: `0 -> 5`
- Reasoning confidence: `0.00 -> 1.00`
- Recommendation: `investable -> investable`