import logging
from collections.abc import Callable

from app.collectors.industry_collector import collect_fred_semiconductor_indicators
from app.collectors.macro_collector import collect_customs_trade, collect_kosis_stats
from app.collectors.market_collector import (
    collect_ecos_exchange_rate,
    collect_global_stock_prices,
    collect_krx_daily,
    collect_krx_investor_flows,
)


def _run_step(name: str, fn: Callable[[], None]) -> None:
    log = logging.getLogger("run_data_boost_once")
    log.info("Data boost step start: %s", name)
    try:
        fn()
    except Exception as e:
        log.exception("Data boost step failed: %s | %s", name, e)
    else:
        log.info("Data boost step done: %s", name)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    _run_step("krx_daily", collect_krx_daily)
    _run_step("krx_investor_flows", collect_krx_investor_flows)
    _run_step("global_stock_prices", collect_global_stock_prices)
    _run_step("ecos_exchange_rate", collect_ecos_exchange_rate)
    _run_step("fred_semiconductor_indicators", collect_fred_semiconductor_indicators)
    _run_step("customs_trade", collect_customs_trade)
    _run_step("kosis_stats", collect_kosis_stats)
    print("[OK] Data boost one-shot collection complete")


if __name__ == "__main__":
    main()
