from __future__ import annotations

import json
import logging
import os
import sys

from app.rag.tech_potential_benchmark import save_tech_potential_benchmark_report


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    limit = int(os.getenv("TECH_POTENTIAL_BENCHMARK_LIMIT", "8"))
    report = save_tech_potential_benchmark_report(limit=limit)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
