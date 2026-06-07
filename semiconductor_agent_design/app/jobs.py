import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.collectors.dart_collector import collect_dart_new_filings, collect_dart_quarterly
from app.collectors.company_official_collector import collect_company_official_sources
from app.collectors.industry_collector import (
    collect_wsts_bluebook,
    collect_industry_press_metrics,
    collect_semiconductor_prices,
    collect_fred_semiconductor_indicators,
)
from app.collectors.knowledge_collector import (
    collect_hotchips_materials,
    collect_equipment_docs,
    collect_semi_vendor_blogs,
    download_irds_new_edition,
    download_jedec_updates,
)
from app.collectors.macro_collector import collect_customs_trade, collect_kosis_stats
from app.collectors.market_collector import (
    collect_ecos_exchange_rate,
    collect_krx_daily,
    collect_krx_investor_flows,
    collect_global_stock_prices,
    collect_global_earnings,
)
from app.collectors.news_collector import collect_rss_all_sources, collect_tech_blogs
from app.collectors.paper_collector import (
    collect_semantic_scholar_weekly,
    collect_openalex_papers,
    collect_openalex_company_priority_papers,
    monitor_arxiv_new_papers,
    monitor_arxiv_company_papers,
)
from app.collectors.patent_collector import collect_kipris_patents
from app.db.neo4j_db import ensure_constraints
from app.db.qdrant import ensure_collection
from app.db.schema import ensure_postgres_schema


QDRANT_COLLECTIONS = [
    "irds_chunks",
    "jedec_chunks",
    "paper_chunks",
    "tech_blog_chunks",
    "news_chunks",
]


def bootstrap() -> None:
    ensure_postgres_schema()
    for name in QDRANT_COLLECTIONS:
        ensure_collection(name)
    ensure_constraints()


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=settings.tz)

    scheduler.add_job(collect_dart_new_filings, CronTrigger(minute="*/10", hour="9-18"), id="dart_poll")
    scheduler.add_job(collect_rss_all_sources, CronTrigger(minute="*/30"), id="rss_poll")
    scheduler.add_job(collect_company_official_sources, CronTrigger(hour=8, minute=10), id="company_official_daily")
    scheduler.add_job(collect_krx_daily, CronTrigger(hour=16, minute=10), id="krx_daily")
    scheduler.add_job(collect_krx_investor_flows, CronTrigger(hour=16, minute=25), id="krx_investor_flows")
    scheduler.add_job(collect_ecos_exchange_rate, CronTrigger(hour=11, minute=0), id="ecos_daily")
    scheduler.add_job(collect_global_stock_prices, CronTrigger(hour=22, minute=30), id="global_stock_daily")
    scheduler.add_job(collect_semiconductor_prices, CronTrigger(hour=9, minute=0), id="semi_price_daily")
    scheduler.add_job(monitor_arxiv_new_papers, CronTrigger(hour=6, minute=0), id="arxiv_daily")
    scheduler.add_job(monitor_arxiv_company_papers, CronTrigger(hour=6, minute=20), id="arxiv_company_daily")
    scheduler.add_job(collect_openalex_company_priority_papers, CronTrigger(hour=6, minute=40), id="openalex_company_daily")

    scheduler.add_job(collect_tech_blogs, CronTrigger(day_of_week="tue,fri", hour=8, minute=0), id="tech_blog_weekly")
    scheduler.add_job(collect_equipment_docs, CronTrigger(day_of_week="mon,thu", hour=8, minute=30), id="equip_docs_weekly")
    scheduler.add_job(collect_semi_vendor_blogs, CronTrigger(day_of_week="wed,sat", hour=8, minute=30), id="semi_blogs_weekly")
    scheduler.add_job(collect_semantic_scholar_weekly, CronTrigger(day_of_week="wed", hour=7, minute=0), id="semantic_weekly")
    scheduler.add_job(collect_openalex_papers, CronTrigger(day_of_week="tue,sat", hour=6, minute=0), id="openalex_semi")
    scheduler.add_job(collect_kipris_patents, CronTrigger(day_of_week="mon", hour=7, minute=0), id="kipris_weekly")

    scheduler.add_job(collect_kosis_stats, CronTrigger(day=15, hour=9, minute=0), id="kosis_monthly")
    scheduler.add_job(collect_customs_trade, CronTrigger(day=20, hour=9, minute=0), id="customs_monthly")
    scheduler.add_job(collect_wsts_bluebook, CronTrigger(day=28, hour=9, minute=0), id="wsts_monthly")
    scheduler.add_job(collect_industry_press_metrics, CronTrigger(day=1, hour=10, minute=0), id="industry_pr_monthly")
    scheduler.add_job(download_jedec_updates, CronTrigger(day=1, hour=7, minute=0), id="jedec_monthly")

    scheduler.add_job(collect_global_earnings, CronTrigger(month="2,5,8,11", day=10, hour=7, minute=0), id="global_earnings_quarterly")
    scheduler.add_job(collect_fred_semiconductor_indicators, CronTrigger(day=5, hour=8, minute=0), id="fred_monthly")
    scheduler.add_job(collect_dart_quarterly, CronTrigger(month="2,5,8,11", day=15, hour=9, minute=0), id="dart_quarterly")
    scheduler.add_job(download_irds_new_edition, CronTrigger(month=11, day=1, hour=9, minute=0), id="irds_yearly")
    scheduler.add_job(collect_hotchips_materials, CronTrigger(month=8, day=20, hour=9, minute=0), id="hotchips_yearly")

    return scheduler


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    bootstrap()
    scheduler = build_scheduler()
    print("Scheduler started (Asia/Seoul). Press Ctrl+C to exit.")
    scheduler.start()


if __name__ == "__main__":
    main()
