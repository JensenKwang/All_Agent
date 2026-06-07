import argparse

from app.rag.diagnostics import print_rag_diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAG infrastructure diagnostics.")
    parser.add_argument("--load-model", action="store_true", help="Also load BGE-M3 and encode a sample query")
    args = parser.parse_args()
    print_rag_diagnostics(load_model=args.load_model)


if __name__ == "__main__":
    main()
