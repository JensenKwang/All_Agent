from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.agent.semiconductor_react import render_bounded_react_summary, run_bounded_semiconductor_react


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the semiconductor bounded ReAct demo.")
    parser.add_argument("question", help="Question to analyze.")
    parser.add_argument("--company", default="", help="Company code, e.g. 005930")
    parser.add_argument("--domain", default="", help="Domain hint, e.g. hbm")
    parser.add_argument("--horizon", type=int, default=30, help="Forecast horizon in days.")
    parser.add_argument("--max-steps", type=int, default=3, help="Maximum bounded ReAct steps.")
    parser.add_argument("--top-k", type=int, default=8, help="Top-k evidence items.")
    parser.add_argument("--dry-run", action="store_true", help="Skip the final LLM assessment and show only tool flow.")
    parser.add_argument("--save", default="", help="Optional markdown output path.")
    args = parser.parse_args()

    state = run_bounded_semiconductor_react(
        args.question,
        company=args.company,
        domain=args.domain,
        horizon_days=args.horizon,
        max_steps=args.max_steps,
        top_k=args.top_k,
        finalize=not args.dry_run,
    )
    summary = render_bounded_react_summary(state)
    print(summary)
    print()
    print(json.dumps(asdict(state), ensure_ascii=False, indent=2))

    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(summary + "\n\n```json\n" + json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
        print(f"[saved] {out}")


if __name__ == "__main__":
    main()
