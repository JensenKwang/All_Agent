import logging
import os
import time
from datetime import datetime, timedelta, timezone

from app.collectors.news_collector import collect_rss_all_sources, collect_tech_blogs
from app.collectors.paper_collector import (
    monitor_arxiv_new_papers,
    monitor_arxiv_company_papers,
    collect_openalex_company_priority_papers,
)


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger(__name__)

    harvest_days = _get_int("TECH_HARVEST_DAYS", 4)
    rss_interval_min = _get_int("TECH_RSS_INTERVAL_MIN", 30)
    arxiv_interval_hour = _get_int("TECH_ARXIV_INTERVAL_HOURS", 6)
    loop_sleep_sec = _get_int("TECH_LOOP_SLEEP_SEC", 30)

    start = datetime.now(timezone.utc)
    end = start + timedelta(days=harvest_days)
    next_rss = start
    next_arxiv = start

    logger.info(
        "Tech harvest start | days=%s rss_interval_min=%s arxiv_interval_hours=%s end=%s",
        harvest_days,
        rss_interval_min,
        arxiv_interval_hour,
        end.isoformat(),
    )

    while True:
        now = datetime.now(timezone.utc)
        if now >= end:
            logger.info("Tech harvest finished | now=%s end=%s", now.isoformat(), end.isoformat())
            break

        if now >= next_rss:
            logger.info("Tech harvest cycle | running RSS+tech blogs")
            try:
                collect_rss_all_sources()
                collect_tech_blogs()
            except Exception as e:
                logger.exception("RSS/tech blog cycle failed: %s", e)
            next_rss = now + timedelta(minutes=rss_interval_min)
            logger.info("Tech harvest cycle | next_rss=%s", next_rss.isoformat())

        if now >= next_arxiv:
            logger.info("Tech harvest cycle | running arXiv")
            try:
                monitor_arxiv_new_papers()
                monitor_arxiv_company_papers()
                collect_openalex_company_priority_papers()
            except Exception as e:
                logger.exception("arXiv cycle failed: %s", e)
            next_arxiv = now + timedelta(hours=arxiv_interval_hour)
            logger.info("Tech harvest cycle | next_arxiv=%s", next_arxiv.isoformat())

        time.sleep(loop_sleep_sec)

    print("[OK] Semiconductor tech harvest complete")


if __name__ == "__main__":
    main()
