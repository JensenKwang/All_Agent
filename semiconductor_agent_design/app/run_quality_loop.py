import logging
from collections.abc import Callable

from app.collectors.company_official_collector import collect_company_official_sources
from app.collectors.industry_collector import collect_fred_semiconductor_indicators
from app.collectors.macro_collector import collect_customs_trade, collect_kosis_stats
from app.collectors.market_collector import (
    collect_ecos_exchange_rate,
    collect_global_stock_prices,
    collect_krx_daily,
    collect_krx_investor_flows,
)
from app.db.schema import ensure_postgres_schema
from app.experience import build_forecast_experience_memory
from app.events.builder import build_event_dataset
from app.forecast.price_forecast import evaluate_due_forecasts, generate_price_forecasts
from app.rag.evaluator import evaluate_rag
from app.rag.indexer import index_all_chunks_safe


def _step(name: str, fn: Callable[[], object]) -> object | None:
    log = logging.getLogger("quality_loop")
    log.info("STEP START | %s", name)
    try:
        result = fn()
    except Exception as e:
        log.exception("STEP FAILED | %s | %s", name, e)
        return None
    log.info("STEP DONE | %s | %s", name, result)
    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    results = {}
    results["schema"] = _step("schema", ensure_postgres_schema)
    results["company_official"] = _step("company_official", collect_company_official_sources)
    results["krx_daily"] = _step("krx_daily", collect_krx_daily)
    results["krx_investor_flows"] = _step("krx_investor_flows", collect_krx_investor_flows)
    results["global_stock_prices"] = _step("global_stock_prices", collect_global_stock_prices)
    results["ecos_exchange_rate"] = _step("ecos_exchange_rate", collect_ecos_exchange_rate)
    results["fred"] = _step("fred", collect_fred_semiconductor_indicators)
    results["customs_trade"] = _step("customs_trade", collect_customs_trade)
    results["kosis"] = _step("kosis", collect_kosis_stats)
    results["events"] = _step("events", build_event_dataset)
    results["reindex"] = _step("reindex", index_all_chunks_safe)
    results["rag_eval"] = _step("rag_eval", evaluate_rag)
    results["price_forecasts"] = _step("price_forecasts", lambda: generate_price_forecasts())
    results["price_forecast_eval"] = _step("price_forecast_eval", evaluate_due_forecasts)
    results["experience_memory"] = _step("experience_memory", build_forecast_experience_memory)

    print("[QUALITY_LOOP_RESULT]")
    print(results)


if __name__ == "__main__":
    main()
