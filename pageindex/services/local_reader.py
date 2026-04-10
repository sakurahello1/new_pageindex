from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf


@dataclass
class PageIndexDocument:
    source_path: Path
    structure_path: Path
    doc_name: str
    structure: list[dict[str, Any]]
    source_kind: str

    @classmethod
    def load(cls, source_path: str | Path, structure_path: str | Path) -> "PageIndexDocument":
        source = Path(source_path).expanduser().resolve()
        structure = Path(structure_path).expanduser().resolve()
        with structure.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        return cls(
            source_path=source,
            structure_path=structure,
            doc_name=payload.get("doc_name") or source.name,
            structure=payload.get("structure", []),
            source_kind="markdown" if source.suffix.lower() in {".md", ".markdown"} else "pdf",
        )

    def render_tree(self, max_depth: int = 4, max_nodes: int = 200) -> str:
        lines: list[str] = [f"Document: {self.doc_name}"]
        count = 0

        def walk(nodes: list[dict[str, Any]], depth: int) -> None:
            nonlocal count
            if depth > max_depth or count >= max_nodes:
                return
            for node in nodes:
                if count >= max_nodes:
                    return
                start_ref, end_ref = _normalize_span(node, self.source_kind)
                unit = "lines" if self.source_kind == "markdown" else "pages"
                lines.append(
                    "  " * depth
                    + f"- [{node.get('node_id', '----')}] {node.get('title', 'Untitled')} ({unit} {start_ref}-{end_ref})"
                )
                count += 1
                walk(node.get("nodes", []), depth + 1)

        walk(self.structure, 0)
        if count >= max_nodes:
            lines.append(f"... truncated after {max_nodes} nodes")
        return "\n".join(lines)

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        for node in self.iter_nodes():
            if node.get("node_id") == node_id:
                return node
        return None

    def iter_nodes(self) -> list[dict[str, Any]]:
        flat: list[dict[str, Any]] = []

        def walk(nodes: list[dict[str, Any]], parents: list[str]) -> None:
            for node in nodes:
                current = dict(node)
                current["path"] = " > ".join(parents + [node.get("title", "Untitled")])
                current["children"] = [
                    {
                        "node_id": child.get("node_id"),
                        "title": child.get("title"),
                        "start_index": child.get("start_index"),
                        "end_index": child.get("end_index"),
                    }
                    for child in node.get("nodes", [])
                ]
                flat.append(current)
                walk(node.get("nodes", []), parents + [node.get("title", "Untitled")])

        walk(self.structure, [])
        return flat

    def describe_node(self, node_id: str) -> str:
        node = self.get_node(node_id)
        if not node:
            return f"Node {node_id} not found."
        start_ref, end_ref = _normalize_span(node, self.source_kind)
        flat = next(item for item in self.iter_nodes() if item.get("node_id") == node_id)
        label = "lines" if self.source_kind == "markdown" else "pages"
        lines = [
            f"node_id: {node.get('node_id')}",
            f"title: {node.get('title', 'Untitled')}",
            f"path: {flat['path']}",
            f"{label}: {start_ref}-{end_ref}",
        ]
        children = flat.get("children", [])
        if children:
            lines.append("children:")
            for child in children:
                child_start, child_end = _normalize_span(child, self.source_kind)
                lines.append(
                    f"- [{child.get('node_id', '----')}] {child.get('title', 'Untitled')} ({label} {child_start}-{child_end})"
                )
        else:
            lines.append("children: none")
        return "\n".join(lines)

    def read_node(self, node_id: str, max_chars: int = 6000) -> str:
        node = self.get_node(node_id)
        if not node:
            return f"Node {node_id} not found."
        start_ref, end_ref = _normalize_span(node, self.source_kind)
        node_text = self.read_pages(start_ref, end_ref, max_chars=max_chars)
        flat = next(item for item in self.iter_nodes() if item.get("node_id") == node_id)
        label = "lines" if self.source_kind == "markdown" else "pages"
        return "\n".join(
            [
                f"node_id: {node.get('node_id')}",
                f"title: {node.get('title', 'Untitled')}",
                f"path: {flat['path']}",
                f"{label}: {start_ref}-{end_ref}",
                "",
                node_text,
            ]
        )

    def read_pages(self, start_page: int, end_page: int, max_chars: int = 6000) -> str:
        start_page, end_page = sorted((int(start_page), int(end_page)))
        if start_page < 1:
            raise ValueError("Start index must be >= 1.")
        if self.source_kind == "markdown":
            return self._read_markdown_lines(start_page, end_page, max_chars=max_chars)
        chunks: list[str] = []
        with pymupdf.open(self.source_path) as pdf:
            if end_page > pdf.page_count:
                raise ValueError(f"Requested page {end_page}, but document only has {pdf.page_count} pages.")
            for page_number in range(start_page, end_page + 1):
                page_text = pdf.load_page(page_number - 1).get_text("text").strip()
                chunks.append(f"[Page {page_number}]\n{page_text}")
        text = "\n\n".join(chunks).strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n\n...[truncated]"

    def _read_markdown_lines(self, start_line: int, end_line: int, max_chars: int = 6000) -> str:
        lines = self.source_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if end_line > len(lines):
            raise ValueError(f"Requested line {end_line}, but document only has {len(lines)} lines.")
        chunks = []
        for line_no in range(start_line, end_line + 1):
            chunks.append(f"{line_no:04d}: {lines[line_no - 1]}")
        text = "\n".join(chunks).strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n\n...[truncated]"


def _normalize_span(node: dict[str, Any], source_kind: str) -> tuple[int, int]:
    if source_kind == "markdown":
        start_line = int(node.get("start_index") or node.get("line_num") or 1)
        end_line = int(node.get("end_index") or (start_line + _text_line_count(node.get("text", "")) - 1))
        if end_line < start_line:
            start_line, end_line = end_line, start_line
        return start_line, end_line
    start_page = int(node.get("start_index", 1))
    end_page = int(node.get("end_index", start_page))
    if end_page < start_page:
        start_page, end_page = end_page, start_page
    return start_page, end_page


def _text_line_count(text: str) -> int:
    if not text:
        return 1
    return max(1, text.count("\n") + 1)
