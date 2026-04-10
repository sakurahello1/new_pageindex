import argparse
from pathlib import Path

from pageindex.services import IngestService


def main():
    parser = argparse.ArgumentParser(description="Ingest PDFs/Markdown and use literature preprocessing for papers and patents when detected.")
    parser.add_argument("paths", nargs="+", help="Files or directories to ingest.")
    parser.add_argument("--workspace", default="workspace", help="Workspace for normalized files, trees, and state.")
    parser.add_argument("--model", default=None, help="Model used by PageIndex fallback tree generation.")
    parser.add_argument("--force", action="store_true", help="Regenerate existing outputs.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    service = IngestService(repo_root=repo_root, workspace_root=args.workspace, **({"model_name": args.model} if args.model else {}))
    sources = service.build_inventory(args.paths)
    records = service.ingest_sources(sources, force=args.force)
    for record in records:
        print(f"{record['document_type']}: {record['structure_path']}")


if __name__ == "__main__":
    main()
