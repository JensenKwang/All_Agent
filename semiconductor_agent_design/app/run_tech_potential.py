from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from app.agent.tech_potential import (
    assess_technology_potential,
    render_technology_potential_markdown,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Assess semiconductor technology impact for near-term price relevance.")
    parser.add_argument("topic", help="Technology topic or question, e.g. 'HBM catalyst and demand'")
    parser.add_argument("--company", default="", help="Optional company hint, e.g. 000660 or ASML")
    parser.add_argument("--domain", default="", help="Optional domain hint, e.g. hbm / litho / packaging")
    parser.add_argument("--top-k", type=int, default=8, help="Evidence items to retrieve")
    parser.add_argument("--markdown", action="store_true", help="Print markdown report after JSON")
    args = parser.parse_args()

    assessment = assess_technology_potential(
        args.topic,
        company_hint=args.company,
        domain_hint=args.domain,
        top_k=args.top_k,
    )

    print(json.dumps(asdict(assessment), ensure_ascii=False, indent=2, default=str))
    if args.markdown:
        print()
        print(render_technology_potential_markdown(assessment))


if __name__ == "__main__":
    main()
