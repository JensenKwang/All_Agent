from __future__ import annotations

import json
import sys
from dataclasses import asdict

from app.agent.semiconductor_tools import get_tool_inventory


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    payload = [asdict(item) for item in get_tool_inventory()]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
