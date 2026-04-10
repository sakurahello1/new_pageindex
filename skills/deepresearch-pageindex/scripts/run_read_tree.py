import argparse

from pageindex.services.local_reader import PageIndexDocument


def main():
    parser = argparse.ArgumentParser(description="Read source text through a PageIndex structure tree.")
    parser.add_argument("--source_path", required=True, help="Path to the original PDF or Markdown file.")
    parser.add_argument("--structure_path", required=True, help="Path to the *_structure.json tree file.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--node_id", help="Read one tree node by node_id.")
    group.add_argument("--pages", help="Read a PDF page range, for example 3 or 3-5.")
    parser.add_argument("--max_chars", type=int, default=6000, help="Maximum characters to print.")
    args = parser.parse_args()

    document = PageIndexDocument.load(source_path=args.source_path, structure_path=args.structure_path)
    if args.node_id:
        print(document.read_node(args.node_id, max_chars=args.max_chars))
        return

    start, end = _parse_range(args.pages)
    print(document.read_pages(start, end, max_chars=args.max_chars))


def _parse_range(value: str) -> tuple[int, int]:
    raw = str(value or "").strip()
    if "-" not in raw:
        page = int(raw)
        return page, page
    start, end = raw.split("-", 1)
    return int(start.strip()), int(end.strip())


if __name__ == "__main__":
    main()
