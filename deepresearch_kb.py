from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

from pageindex.services import IngestService, PageIndexDocument


SUPPORTED_EXTENSIONS = {".pdf", ".md", ".markdown", ".txt", ".docx", ".doc"}
REGISTRY_FILENAME = "registry.json"


@dataclass
class KnowledgeBase:
    root: Path

    @property
    def registry_path(self) -> Path:
        return self.root / REGISTRY_FILENAME

    @property
    def documents_dir(self) -> Path:
        return self.root / "documents"

    @property
    def trees_dir(self) -> Path:
        return self.root / "trees"

    @property
    def pageindex_workspace(self) -> Path:
        return self.root / "_pageindex"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="DeepResearch PageIndex knowledge-base CLI.")
    parser.add_argument("--kb", default="knowledge_base", help="Knowledge-base directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize a knowledge base.")

    add_parser = subparsers.add_parser("add", help="Add a document and generate its tree.")
    add_parser.add_argument("--name", required=True, help="Stable document name used by later commands.")
    add_parser.add_argument("--source", required=True, help="Local path or HTTP(S) URL to PDF, Markdown, text, or Word file.")
    add_parser.add_argument("--model", default=None, help="Model used for PDF/PageIndex fallback tree generation.")
    add_parser.add_argument("--force", action="store_true", help="Replace an existing document with the same name.")

    list_parser = subparsers.add_parser("list", help="List documents in the knowledge base.")
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    tree_parser = subparsers.add_parser("tree", help="List one document's tree.")
    tree_parser.add_argument("--name", required=True, help="Document name.")
    tree_parser.add_argument("--max-depth", type=int, default=6, help="Maximum tree depth to print.")
    tree_parser.add_argument("--max-nodes", type=int, default=500, help="Maximum tree nodes to print.")

    read_parser = subparsers.add_parser("read", help="Read one or more document parts.")
    read_parser.add_argument("--name", required=True, help="Document name.")
    read_parser.add_argument("--node", action="append", default=[], help="Node id to read. Can be repeated.")
    read_parser.add_argument("--range", action="append", default=[], help="Page or line range, e.g. 3 or 3-5. Can be repeated.")
    read_parser.add_argument("--max-chars", type=int, default=6000, help="Maximum characters per part.")

    args = parser.parse_args()
    kb = KnowledgeBase(Path(args.kb).expanduser().resolve())

    if args.command == "init":
        init_kb(kb)
    elif args.command == "add":
        add_document(kb, name=args.name, source=args.source, model=args.model, force=args.force)
    elif args.command == "list":
        list_documents(kb, as_json=args.json)
    elif args.command == "tree":
        print_tree(kb, name=args.name, max_depth=args.max_depth, max_nodes=args.max_nodes)
    elif args.command == "read":
        read_parts(kb, name=args.name, nodes=args.node, ranges=args.range, max_chars=args.max_chars)


def init_kb(kb: KnowledgeBase) -> None:
    kb.root.mkdir(parents=True, exist_ok=True)
    kb.documents_dir.mkdir(parents=True, exist_ok=True)
    kb.trees_dir.mkdir(parents=True, exist_ok=True)
    kb.pageindex_workspace.mkdir(parents=True, exist_ok=True)
    if not kb.registry_path.exists():
        _save_registry(kb, {"version": 1, "documents": {}})
    print(f"Initialized knowledge base: {kb.root}")


def add_document(kb: KnowledgeBase, *, name: str, source: str, model: str | None, force: bool) -> None:
    init_kb(kb)
    doc_name = _normalize_doc_name(name)
    registry = _load_registry(kb)
    if doc_name in registry["documents"] and not force:
        raise SystemExit(f"Document already exists: {doc_name}. Use --force to replace it.")

    source_path = _resolve_source(source, kb.root / "_tmp")
    stored_source = _store_source(kb, doc_name, source_path)
    content_path, structure_path, metadata = _build_document_tree(kb, doc_name, stored_source, model=model, force=force)

    registry["documents"][doc_name] = {
        "name": doc_name,
        "original_source": source,
        "source_path": str(content_path),
        "structure_path": str(structure_path),
        "source_type": content_path.suffix.lower().lstrip("."),
        "metadata": metadata,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_registry(kb, registry)
    print(json.dumps(registry["documents"][doc_name], ensure_ascii=False, indent=2))


def list_documents(kb: KnowledgeBase, *, as_json: bool) -> None:
    registry = _require_registry(kb)
    documents = list(registry.get("documents", {}).values())
    documents.sort(key=lambda item: item["name"])
    if as_json:
        print(json.dumps(documents, ensure_ascii=False, indent=2))
        return
    if not documents:
        print("No documents.")
        return
    for doc in documents:
        metadata = doc.get("metadata", {})
        kind = metadata.get("literature_kind") or metadata.get("document_type") or doc.get("source_type")
        print(f"{doc['name']}\t{kind}\t{doc['source_path']}")


def print_tree(kb: KnowledgeBase, *, name: str, max_depth: int, max_nodes: int) -> None:
    doc = _get_document(kb, name)
    document = PageIndexDocument.load(source_path=doc["source_path"], structure_path=doc["structure_path"])
    print(document.render_tree(max_depth=max_depth, max_nodes=max_nodes))


def read_parts(kb: KnowledgeBase, *, name: str, nodes: list[str], ranges: list[str], max_chars: int) -> None:
    if not nodes and not ranges:
        raise SystemExit("Provide at least one --node or --range.")
    doc = _get_document(kb, name)
    document = PageIndexDocument.load(source_path=doc["source_path"], structure_path=doc["structure_path"])
    outputs: list[str] = []
    for node_id in nodes:
        outputs.append(_part_header(f"node {node_id}") + document.read_node(node_id=node_id, max_chars=max_chars))
    for value in ranges:
        start, end = _parse_range(value)
        outputs.append(_part_header(f"range {start}-{end}") + document.read_pages(start, end, max_chars=max_chars))
    print("\n\n".join(outputs))


def _build_document_tree(kb: KnowledgeBase, doc_name: str, source_path: Path, *, model: str | None, force: bool) -> tuple[Path, Path, dict[str, Any]]:
    suffix = source_path.suffix.lower()
    metadata: dict[str, Any] = {"document_type": suffix.lstrip(".")}

    if suffix in {".pdf", ".md", ".markdown"}:
        content_path = source_path
    elif suffix == ".txt":
        content_path = _txt_to_markdown(kb, doc_name, source_path)
    elif suffix in {".docx", ".doc"}:
        content_path = _word_to_markdown(kb, doc_name, source_path)
    else:
        raise SystemExit(f"Unsupported document format: {suffix}")

    service = IngestService(
        repo_root=Path(__file__).resolve().parent,
        workspace_root=kb.pageindex_workspace / doc_name,
        **({"model_name": model} if model else {}),
    )
    record = service.ingest_path(content_path, force=force)
    content_path = Path(record["content_path"]).resolve()
    generated_tree = Path(record["structure_path"]).resolve()
    structure_path = kb.trees_dir / f"{doc_name}_structure.json"
    shutil.copy2(generated_tree, structure_path)
    metadata.update(record.get("metadata") or {})
    metadata["document_type"] = record.get("document_type") or metadata["document_type"]
    if suffix in {".txt", ".docx", ".doc"}:
        metadata["conversion_source_type"] = suffix.lstrip(".")
        metadata["normalized_to"] = "markdown"
    return content_path, structure_path, metadata


def _resolve_source(source: str, tmp_dir: Path) -> Path:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        response = requests.get(source, timeout=120)
        response.raise_for_status()
        filename = _filename_from_url(parsed.path, response.headers.get("Content-Type", ""))
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise SystemExit(f"Unsupported URL file extension: {suffix}")
        target = tmp_dir / filename
        target.write_bytes(response.content)
        return target

    path = Path(source).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise SystemExit(f"Source file not found: {source}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise SystemExit(f"Unsupported document format: {path.suffix}")
    return path


def _filename_from_url(url_path: str, content_type: str) -> str:
    raw_name = Path(url_path).name or "downloaded"
    raw_suffix = Path(raw_name).suffix.lower()
    if re.match(r"^\d{4}\.\d{4,5}(?:v\d+)?$", raw_name, re.IGNORECASE):
        return f"{raw_name}.pdf"
    if raw_suffix in SUPPORTED_EXTENSIONS:
        return raw_name
    if "application/pdf" in content_type.lower():
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_name).strip("._") or "downloaded"
        return f"{safe_name}.pdf"
    return raw_name


def _store_source(kb: KnowledgeBase, doc_name: str, source_path: Path) -> Path:
    suffix = source_path.suffix.lower()
    target = kb.documents_dir / f"{doc_name}{suffix}"
    shutil.copy2(source_path, target)
    return target


def _txt_to_markdown(kb: KnowledgeBase, doc_name: str, source_path: Path) -> Path:
    text = source_path.read_text(encoding="utf-8", errors="ignore")
    target = kb.documents_dir / f"{doc_name}.md"
    target.write_text(f"# {doc_name}\n\n{text.strip()}\n", encoding="utf-8")
    return target


def _word_to_markdown(kb: KnowledgeBase, doc_name: str, source_path: Path) -> Path:
    if source_path.suffix.lower() == ".docx":
        text = _extract_docx_text(source_path)
    else:
        text = _extract_doc_text_with_word(source_path)
    target = kb.documents_dir / f"{doc_name}.md"
    target.write_text(f"# {doc_name}\n\n{text.strip()}\n", encoding="utf-8")
    return target


def _extract_docx_text(path: Path) -> str:
    try:
        from docx import Document

        document = Document(str(path))
        return "\n\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())
    except Exception:
        return _extract_docx_text_from_xml(path)


def _extract_docx_text_from_xml(path: Path) -> str:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        runs = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        text = "".join(runs).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _extract_doc_text_with_word(path: Path) -> str:
    try:
        import win32com.client
    except Exception as exc:
        raise SystemExit(".doc files require Microsoft Word automation via pywin32 on Windows, or convert the file to .docx first.") from exc

    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(str(path.resolve()))
        try:
            return str(doc.Content.Text)
        finally:
            doc.Close(False)
    finally:
        word.Quit()


def _build_markdown_tree(source_path: Path, structure_path: Path, title: str) -> None:
    lines = source_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    headings: list[dict[str, Any]] = []
    in_code_block = False
    for line_no, line in enumerate(lines, start=1):
        clean_line = line.lstrip("\ufeff")
        if clean_line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", clean_line)
        if match:
            headings.append({"level": len(match.group(1)), "title": match.group(2).strip(), "start_index": line_no})
    if not headings:
        headings = [{"level": 1, "title": title, "start_index": 1}]
    for idx, item in enumerate(headings):
        end_index = len(lines)
        for other in headings[idx + 1 :]:
            if other["level"] <= item["level"]:
                end_index = max(item["start_index"], other["start_index"] - 1)
                break
        item["end_index"] = end_index
    payload = {"doc_name": title, "structure": _nest_heading_nodes(headings)}
    structure_path.parent.mkdir(parents=True, exist_ok=True)
    structure_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _nest_heading_nodes(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for idx, item in enumerate(headings, start=1):
        node = {
            "node_id": f"md_{idx:04d}",
            "title": item["title"],
            "start_index": item["start_index"],
            "end_index": item["end_index"],
            "summary": "",
            "nodes": [],
        }
        while stack and stack[-1]["level"] >= item["level"]:
            stack.pop()
        if stack:
            stack[-1]["node"]["nodes"].append(node)
        else:
            roots.append(node)
        stack.append({"level": item["level"], "node": node})
    return roots


def _load_registry(kb: KnowledgeBase) -> dict[str, Any]:
    if not kb.registry_path.exists():
        return {"version": 1, "documents": {}}
    payload = json.loads(kb.registry_path.read_text(encoding="utf-8"))
    payload.setdefault("version", 1)
    payload.setdefault("documents", {})
    return payload


def _require_registry(kb: KnowledgeBase) -> dict[str, Any]:
    if not kb.registry_path.exists():
        raise SystemExit(f"Knowledge base is not initialized: {kb.root}")
    return _load_registry(kb)


def _save_registry(kb: KnowledgeBase, payload: dict[str, Any]) -> None:
    kb.root.mkdir(parents=True, exist_ok=True)
    kb.registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_document(kb: KnowledgeBase, name: str) -> dict[str, Any]:
    registry = _require_registry(kb)
    doc_name = _normalize_doc_name(name)
    doc = registry.get("documents", {}).get(doc_name)
    if not doc:
        raise SystemExit(f"Document not found: {doc_name}")
    return doc


def _normalize_doc_name(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        raise SystemExit("--name cannot be empty.")
    if re.search(r"[\\/:\*\?\"<>\|]", value):
        raise SystemExit("--name cannot contain path separators or Windows-reserved filename characters.")
    return value


def _parse_range(value: str) -> tuple[int, int]:
    raw = str(value or "").strip()
    if "-" not in raw:
        page = int(raw)
        return page, page
    start, end = raw.split("-", 1)
    return int(start.strip()), int(end.strip())


def _part_header(label: str) -> str:
    return f"===== {label} =====\n"


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
