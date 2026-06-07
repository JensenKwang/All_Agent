#!/usr/bin/env python
"""
반도체 전문가 에이전트 데모

사용법:
    python run_agent_demo.py
    python run_agent_demo.py "HBM4 hybrid bonding latest paper"  # RAG 자동 탐지
"""
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

from dotenv import load_dotenv
load_dotenv()

if not os.getenv("ANTHROPIC_API_KEY"):
    print("❌ ANTHROPIC_API_KEY가 .env에 없습니다.")
    print("   .env 파일에 ANTHROPIC_API_KEY=your_key_here 추가 후 재실행")
    sys.exit(1)

from app.agent.pipeline import run, run_from_rag
from app.agent.models import TechEvent

if len(sys.argv) > 1:
    # RAG 자동 탐지 모드
    query = " ".join(sys.argv[1:])
    print(f"\n🔍 RAG 탐지 모드: '{query}'\n")
    report = run_from_rag(query)
else:
    # 예시 이벤트 직접 입력
    event = TechEvent(
        title="HBM4 Cu-Cu Hybrid Bonding with Sub-1µm Pitch Interface",
        content="""
        We demonstrate a novel Cu-Cu hybrid bonding process achieving sub-1µm pitch
        for HBM4 integration. The process enables 4x bandwidth density improvement
        over conventional micro-bump approaches. Thermal resistance is reduced by 40%
        due to elimination of solder interfaces. Yield > 99.5% on 300mm wafers.
        Key results: bandwidth density 2TB/s/mm2, junction temperature -15°C vs baseline.
        Partners: SK Hynix process integration team + IMEC advanced packaging division.
        """,
        source_type="paper",
        source="iedm",
        published_at="2025-05-01",
    )
    print(f"\n📄 직접 이벤트 모드\n이벤트: {event.title}\n")
    report = run(event)

# 리포트 출력
print("\n" + "=" * 70)
print(report.full_report)
print("=" * 70)
