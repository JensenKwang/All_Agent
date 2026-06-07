# Overnight Semiconductor Agent Report

- generated_at: `2026-06-01T18:40:07.248342+00:00`
- overnight_hours: `8`

## What Ran

- `krx_daily`: `ok`
- `krx_investor_flows`: `ok`
- `global_stock_prices`: `ok`
- `ecos_exchange_rate`: `ok`
- `fred_semiconductor_indicators`: `ok`
- `customs_trade`: `ok`
- `kosis_stats`: `ok`
- `cycle_1_company_official_sources`: `ok`
- `cycle_1_rss_all_sources`: `ok`
- `cycle_1_tech_blogs`: `ok`
- `cycle_1_arxiv_new_papers`: `ok`
- `cycle_1_arxiv_company_papers`: `ok`
- `cycle_1_openalex_company_priority_papers`: `ok`
- `build_event_dataset`: `ok`
- `index_all_chunks`: `failed`
- `evaluate_rag`: `ok`
- `chunked_backtest`: `ok`
- `build_experience_memory`: `ok`

## Data Snapshot

- tech_documents: `1410`
- tech_document_chunks: `8917`
- event_candidates: `194`
- price_forecasts: `228`
- price_forecast_evaluations: `151`

## RAG Check

- passed: `4/4`
- pass_rate: `100.0%`

## Backtest Progress

- completed_tasks: `2/33`
- pending_tasks: `31`
- ran_cases_this_run: `33`
- checkpoint: `C:\Users\82102\OneDrive\바탕 화면\sc_agent\semiconductor_agent_design\reports\overnight_backtest_checkpoint.json`

## Experience Memory

- case_count: `151`
- partial: `67`
- failure: `59`
- success: `25`

## Top Error Patterns

- `direction_flip`: `68`
- `missing_tech_event_context`: `31`
- `already_priced_in_miss`: `15`
- `volatility_underweighted`: `15`
- `macro_override`: `3`

## Notes

- This report is written by the overnight automation.
- Long backtests are processed in chunks and resume from checkpoint.