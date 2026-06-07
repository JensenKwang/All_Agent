import argparse
import logging

from app.rag.evaluator import print_eval_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG evidence quality.")
    parser.add_argument("--cases", default=None, help="Optional YAML eval cases path")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    print_eval_report(args.cases)


if __name__ == "__main__":
    main()
