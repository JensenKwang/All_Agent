"""
bootstrap_knowledge.py
======================
기술 지식 레이어 최초 1회 부트스트랩.

실행: python bootstrap_knowledge.py [--dry-run] [--irds-only] [--jedec-only] [--blogs-only]
"""

import argparse
import logging
import sys
import os

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

from app.config import settings  # noqa: E402 (dotenv load)


def main():
    parser = argparse.ArgumentParser(description="Knowledge layer bootstrap")
    parser.add_argument("--dry-run", action="store_true", help="Show config but don't collect")
    parser.add_argument("--irds-only", action="store_true")
    parser.add_argument("--jedec-only", action="store_true")
    parser.add_argument("--hotchips-only", action="store_true")
    parser.add_argument("--blogs-only", action="store_true")
    parser.add_argument("--all", action="store_true", help="Full bootstrap (default)")
    args = parser.parse_args()

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    embed_dim = 1536 if openai_key else int(os.getenv("EMBED_DIM", "384"))
    embed_model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small") if openai_key else os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")

    print("=" * 60)
    print("KNOWLEDGE LAYER BOOTSTRAP")
    print(f"  DB:          {settings.postgres_dsn[:40]}...")
    print(f"  Qdrant:      {settings.qdrant_url[:50] if settings.qdrant_url else 'localhost'}")
    print(f"  Embed model: {embed_model} (dim={embed_dim})")
    print(f"  IRDS year:   {os.getenv('IRDS_TARGET_YEAR', '2024')}")
    print(f"  Embed ON:    {os.getenv('KNOWLEDGE_ENABLE_EMBED', '1')}")
    print("=" * 60)

    if args.dry_run:
        print("[DRY RUN] No data collected.")
        return

    from app.collectors.knowledge_collector import (
        ingest_irds_all_editions,
        download_jedec_updates,
        collect_hotchips_materials,
        collect_equipment_docs,
        collect_semi_vendor_blogs,
        bootstrap_knowledge_layer,
    )

    run_all = not any([args.irds_only, args.jedec_only, args.hotchips_only, args.blogs_only])

    if run_all or args.__dict__.get("all"):
        bootstrap_knowledge_layer()
    else:
        if args.irds_only:
            ingest_irds_all_editions()
        if args.jedec_only:
            download_jedec_updates()
        if args.hotchips_only:
            collect_hotchips_materials()
        if args.blogs_only:
            collect_equipment_docs()
            collect_semi_vendor_blogs()


if __name__ == "__main__":
    main()
