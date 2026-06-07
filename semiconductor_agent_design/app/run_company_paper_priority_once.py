from __future__ import annotations

import logging

from app.collectors.paper_collector import (
    collect_openalex_company_priority_papers,
    monitor_arxiv_company_papers,
)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    collect_openalex_company_priority_papers()
    monitor_arxiv_company_papers()
    print("[OK] Company-priority paper harvest complete")


if __name__ == "__main__":
    main()
