import logging
from collections.abc import Callable

from app.collectors.company_official_collector import collect_company_official_sources
from app.collectors.news_collector import collect_rss_all_sources, collect_tech_blogs
from app.collectors.paper_collector import (
    monitor_arxiv_new_papers,
    monitor_arxiv_company_papers,
    collect_openalex_company_priority_papers,
)


def _run_step(name: str, fn: Callable[[], None]) -> None:
    log = logging.getLogger("run_tech_once")
    log.info("Tech collection step start: %s", name)
    try:
        fn()
    except Exception as e:
        log.exception("Tech collection step failed: %s | %s", name, e)
    else:
        log.info("Tech collection step done: %s", name)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    _run_step("company_official_sources", collect_company_official_sources)
    _run_step("rss_all_sources", collect_rss_all_sources)
    _run_step("tech_blogs", collect_tech_blogs)
    _run_step("arxiv_new_papers", monitor_arxiv_new_papers)
    _run_step("arxiv_company_papers", monitor_arxiv_company_papers)
    _run_step("openalex_company_priority_papers", collect_openalex_company_priority_papers)
    print("[OK] Semiconductor tech data one-shot collection complete")


if __name__ == "__main__":
    main()
