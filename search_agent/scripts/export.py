"""
AgentResponse DB 데이터를 CSV / JSON으로 내보내기
"""
import csv
import json
from datetime import datetime
from database import SessionLocal
from models import AgentResponse


def export(fmt: str = "csv"):
    db = SessionLocal()
    try:
        rows = db.query(AgentResponse).order_by(AgentResponse.created_at).all()
        if not rows:
            print("저장된 쿼리 결과가 없습니다.")
            return

        data = [
            {
                "id": r.id,
                "model": r.model_name,
                "query": r.query,
                "response": r.response,
                "created_at": str(r.created_at),
            }
            for r in rows
        ]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if fmt == "json":
            path = f"agent_responses_{timestamp}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            path = f"agent_responses_{timestamp}.csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)

        print(f"[완료] {len(data)}건 저장 → {path}")

    finally:
        db.close()


if __name__ == "__main__":
    import sys
    fmt = sys.argv[1] if len(sys.argv) > 1 else "csv"
    export(fmt)
