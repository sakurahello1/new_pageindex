from __future__ import annotations

import json
import os
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf
import requests


PATENT_FILE_RE = re.compile(r"^(?:CN|US|WO|EP|JP|KR)\d", re.IGNORECASE)
ARXIV_FILE_RE = re.compile(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", re.IGNORECASE)
PATENT_TEXT_RE = re.compile(r"(?:专利|patent|申请号|publication\s+number|公开号|公开日|授权公告号)", re.IGNORECASE)
NON_PAPER_TEXT_RE = re.compile(r"(?:申报书|可行性研究|技术方案|立项|结题|中期报告|实施方案)", re.IGNORECASE)
PATENT_TITLE_MARKER_RE = re.compile(r"^\(\s*54\s*\)\s*(?:发明名称|名称)\s*$")
PATENT_DRAWINGS_MARKER_RE = re.compile(r"说\s*明\s*书\s*附\s*图")
PATENT_ABSTRACT_MARKER_RE = re.compile(r"\(\s*57\s*\)\s*摘要|摘\s*要")
PATENT_CLAIMS_MARKER_RE = re.compile(r"权\s*利\s*要\s*求\s*书")
PATENT_INFO_MARKER_RE = re.compile(r"(?:中华人民共和国国家知识产权局|申请号|专利权人|发明人|授权公告号)")
PATENT_HEADINGS = [
    "专利信息",
    "摘要",
    "权利要求书",
    "技术领域",
    "背景技术",
    "发明内容",
    "附图说明",
    "具体实施方式",
    "说明书附图",
]
PATENT_HEADING_RE = re.compile(rf"^(?:{'|'.join(map(re.escape, PATENT_HEADINGS))})\s*$")
PAPER_TEXT_SIGNALS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\barxiv\s*:",
        r"\bdoi\s*:",
        r"\babstract\b",
        r"\breferences\b",
        r"\bintroduction\b",
        r"\bkeywords\b",
        r"\bconference\b",
        r"\bjournal\b",
        r"\bproceedings\b",
    ]
]


@dataclass
class LiteratureDetection:
    is_standard_literature: bool
    literature_kind: str | None = None
    reason: str | None = None


@dataclass
class LiteratureParseResult:
    structure_path: Path
    metadata: dict[str, Any]


def detect_standard_literature(path: str | Path) -> LiteratureDetection:
    source = Path(path).expanduser().resolve()
    name = source.name

    if PATENT_FILE_RE.match(name) or PATENT_TEXT_RE.search(name):
        return LiteratureDetection(True, "patent", "filename_matches_patent_pattern")

    if source.suffix.lower() != ".pdf":
        return LiteratureDetection(False, None, "only_pdf_supported_for_literature_detection")

    first_pages_text = _read_pdf_text_head(source, max_pages=2, max_chars=12000)
    if PATENT_TEXT_RE.search(first_pages_text):
        return LiteratureDetection(True, "patent", "first_pages_contain_patent_markers")

    if NON_PAPER_TEXT_RE.search(name) or NON_PAPER_TEXT_RE.search(first_pages_text):
        return LiteratureDetection(False, None, "document_looks_like_internal_project_material")

    strong_paper_signal = bool(ARXIV_FILE_RE.search(name) or re.search(r"\barxiv\s*:", first_pages_text, re.IGNORECASE))
    paper_signal_count = sum(1 for pattern in PAPER_TEXT_SIGNALS if pattern.search(first_pages_text))
    if strong_paper_signal or paper_signal_count >= 3:
        return LiteratureDetection(True, "paper", "first_pages_match_academic_paper_signals")

    return LiteratureDetection(False, None, "no_reliable_literature_signal")


def prepare_literature_structure(
    pdf_path: str | Path,
    structure_path: str | Path,
    source_pdf_path: str | Path | None = None,
    cache_root: str | Path | None = None,
) -> LiteratureParseResult | None:
    pdf = Path(pdf_path).expanduser().resolve()
    source_pdf = Path(source_pdf_path).expanduser().resolve() if source_pdf_path else pdf
    detection = detect_standard_literature(source_pdf)

    if detection.literature_kind == "patent":
        patent = _prepare_patent_structure_from_pdf(pdf)
        if patent is not None:
            target = Path(structure_path).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps({"doc_name": patent["doc_title"], "structure": patent["structure"]}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return LiteratureParseResult(
                structure_path=target,
                metadata={
                    "title": patent["doc_title"],
                    "preprocess_strategy": "patent_regex_outline",
                    "is_standard_literature": True,
                    "literature_kind": "patent",
                    "literature_outline": patent["outline"],
                    "outline_source": "pdf_regex",
                },
            )

    extracted_dir = _ensure_mineru_output(source_pdf, cache_root=cache_root)
    if extracted_dir is None:
        return None

    headings = _extract_headings(extracted_dir)
    if not headings:
        return None

    page_count = _get_pdf_page_count(pdf)
    doc_title = _extract_document_title(extracted_dir) or pdf.name
    structure = _build_structure_from_headings(headings=headings, page_count=page_count)
    if not structure:
        return None

    target = Path(structure_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"doc_name": doc_title, "structure": structure}, ensure_ascii=False, indent=2), encoding="utf-8")

    return LiteratureParseResult(
        structure_path=target,
        metadata={
            "title": doc_title,
            "preprocess_strategy": "mineru_outline",
            "is_standard_literature": True,
            "literature_kind": detection.literature_kind,
            "mineru_extracted_dir": str(extracted_dir),
            "mineru_full_md_path": _find_first(extracted_dir, ["full.md"]),
            "mineru_layout_path": _find_first(extracted_dir, ["layout.json"]),
            "mineru_content_list_path": _resolve_content_list_path(extracted_dir),
            "literature_outline": [{"title": item["title"], "level": item["level"], "page": item["page"]} for item in headings],
            "outline_source": "mineru_content_list",
        },
    )


def _prepare_patent_structure_from_pdf(pdf_path: Path) -> dict[str, Any] | None:
    doc_title = ""
    outline: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    drawings_pages: list[int] = []
    info_pages: list[int] = []
    abstract_pages: list[int] = []
    claims_pages: list[int] = []

    with pymupdf.open(pdf_path) as doc:
        for page_idx in range(doc.page_count):
            page_no = page_idx + 1
            page_text = doc.load_page(page_idx).get_text("text")
            normalized_page_text = re.sub(r"\s+", "", page_text or "")
            if PATENT_INFO_MARKER_RE.search(page_text or "") and page_no == 1:
                info_pages.append(page_no)
            if PATENT_ABSTRACT_MARKER_RE.search(normalized_page_text) and page_no <= 2:
                abstract_pages.append(page_no)
            if PATENT_CLAIMS_MARKER_RE.search(normalized_page_text):
                claims_pages.append(page_no)
            if PATENT_DRAWINGS_MARKER_RE.search(normalized_page_text):
                drawings_pages.append(page_no)

            lines = [_normalize_title(line) for line in page_text.splitlines()]
            lines = [line for line in lines if line]
            if not doc_title:
                doc_title = _extract_patent_title_from_lines(lines)

            for line_idx, line in enumerate(lines):
                if line in seen_titles or not PATENT_HEADING_RE.match(line):
                    continue
                if line == "摘要" and page_no > 2:
                    continue
                if line == "权利要求书" and page_no > 3:
                    continue
                if line == "说明书附图":
                    continue
                if line in {"技术领域", "背景技术", "发明内容", "附图说明", "具体实施方式"} and page_no < 2:
                    continue
                outline.append({"title": line, "level": 1, "page": page_no, "line_idx": line_idx})
                seen_titles.add(line)

    _append_page_bucket(outline, seen_titles, "专利信息", info_pages, line_idx=-30)
    _append_page_bucket(outline, seen_titles, "摘要", abstract_pages, line_idx=-20)
    _append_page_bucket(outline, seen_titles, "权利要求书", claims_pages, line_idx=-10)
    if drawings_pages and "说明书附图" not in seen_titles:
        outline.append({"title": "说明书附图", "level": 1, "page": min(drawings_pages), "line_idx": 10**6})

    if not outline:
        return None

    outline.sort(key=lambda item: (item["page"], item["line_idx"]))
    normalized_outline = [{"title": item["title"], "level": 1, "page": item["page"]} for item in outline]
    structure = _build_structure_from_headings(normalized_outline, _get_pdf_page_count(pdf_path))
    return {"doc_title": doc_title or pdf_path.name, "outline": normalized_outline, "structure": structure}


def _extract_patent_title_from_lines(lines: list[str]) -> str:
    for idx, line in enumerate(lines):
        if PATENT_TITLE_MARKER_RE.match(line):
            for candidate in lines[idx + 1 : idx + 5]:
                if candidate and candidate not in PATENT_HEADINGS and not candidate.startswith("("):
                    return candidate
    for line in lines:
        if line.startswith("一种"):
            return line
    return ""


def _append_page_bucket(outline: list[dict[str, Any]], seen_titles: set[str], title: str, pages: list[int], *, line_idx: int) -> None:
    if pages and title not in seen_titles:
        outline.append({"title": title, "level": 1, "page": min(pages), "line_idx": line_idx})
        seen_titles.add(title)


def _read_pdf_text_head(pdf_path: Path, max_pages: int, max_chars: int) -> str:
    chunks: list[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page_idx in range(min(max_pages, doc.page_count)):
            text = doc.load_page(page_idx).get_text("text").strip()
            if text:
                chunks.append(text)
            if sum(len(item) for item in chunks) >= max_chars:
                break
    return "\n".join(chunks)[:max_chars]


def _get_pdf_page_count(pdf_path: Path) -> int:
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def _ensure_mineru_output(pdf_path: Path, cache_root: str | Path | None = None) -> Path | None:
    output_root = _mineru_output_root(cache_root)
    extracted_dir = output_root / pdf_path.name / "extracted"
    if extracted_dir.exists():
        return extracted_dir

    token = os.getenv("MINERU_API_TOKEN", "").strip() or os.getenv("MINERU_API_KEY", "").strip()
    if not token:
        return None

    api_base = os.getenv("MINERU_API_BASE", "https://mineru.net/api/v4").rstrip("/")
    output_root.mkdir(parents=True, exist_ok=True)
    apply_resp = _request(
        "POST",
        f"{api_base}/file-urls/batch",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"files": [{"name": pdf_path.name}], "model_version": "vlm"},
        timeout=60,
    )
    apply_resp.raise_for_status()
    apply_data = apply_resp.json().get("data", {})
    batch_id = apply_data.get("batch_id")
    file_urls = apply_data.get("file_urls", [])
    if not batch_id or not file_urls:
        return None

    with pdf_path.open("rb") as handle:
        upload_resp = _request("PUT", file_urls[0], data=handle, timeout=300)
    if not (200 <= upload_resp.status_code < 300):
        return None

    extract_result: dict[str, Any] | None = None
    deadline = time.time() + 240
    while time.time() < deadline:
        poll_resp = _request(
            "GET",
            f"{api_base}/extract-results/batch/{batch_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=60,
        )
        poll_resp.raise_for_status()
        results = poll_resp.json().get("data", {}).get("extract_result", [])
        if results and results[0].get("state") in {"done", "failed"}:
            extract_result = results[0]
            break
        time.sleep(3)

    if not extract_result or extract_result.get("state") != "done":
        return None

    zip_url = extract_result.get("full_zip_url")
    if not zip_url:
        return None

    target_dir = output_root / pdf_path.name
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir / "result.zip"
    with _request("GET", zip_url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with zip_path.open("wb") as handle:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    extracted_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(extracted_dir)
    return extracted_dir


def _request(method: str, url: str, **kwargs) -> requests.Response:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            return requests.request(method, url, **kwargs)
        except Exception as exc:
            last_error = exc
            time.sleep(1.5)
    raise RuntimeError(f"MinerU request failed: {last_error}") from last_error


def _mineru_output_root(cache_root: str | Path | None) -> Path:
    if cache_root:
        return Path(cache_root).expanduser().resolve()
    configured = os.getenv("MINERU_OUTPUT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.cwd().resolve() / "mineru_outputs"


def _resolve_content_list_path(extracted_dir: Path) -> str | None:
    candidates = [extracted_dir / "content_list_v2.json", *sorted(extracted_dir.glob("*_content_list.json"))]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _extract_headings(extracted_dir: Path) -> list[dict[str, Any]]:
    content_list_path = _resolve_content_list_path(extracted_dir)
    if not content_list_path:
        return []

    payload = json.loads(Path(content_list_path).read_text(encoding="utf-8"))
    headings: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()

    if isinstance(payload, list) and payload and isinstance(payload[0], list):
        for page_idx, blocks in enumerate(payload):
            for block in blocks:
                heading = _heading_from_content_block(block, page_idx)
                if heading is not None and (heading["page"], heading["level"], heading["title"]) not in seen:
                    seen.add((heading["page"], heading["level"], heading["title"]))
                    headings.append(heading)
    elif isinstance(payload, list):
        for block in payload:
            page_idx = int(block.get("page_idx", 0))
            heading = _heading_from_flat_block(block, page_idx)
            if heading is not None and (heading["page"], heading["level"], heading["title"]) not in seen:
                seen.add((heading["page"], heading["level"], heading["title"]))
                headings.append(heading)

    return _drop_document_title_heading(headings) if headings else []


def _heading_from_content_block(block: dict[str, Any], page_idx: int) -> dict[str, Any] | None:
    if block.get("type") != "title":
        return None
    content = block.get("content", {})
    title = _normalize_title(_join_fragments(content.get("title_content", [])))
    if not _is_heading_candidate(title):
        return None
    return {"title": title, "level": _infer_heading_level(title, content.get("level")), "page": page_idx + 1}


def _heading_from_flat_block(block: dict[str, Any], page_idx: int) -> dict[str, Any] | None:
    if block.get("text_level") is None:
        return None
    title = _normalize_title(block.get("text", ""))
    if not _is_heading_candidate(title):
        return None
    return {"title": title, "level": _infer_heading_level(title, block.get("text_level")), "page": page_idx + 1}


def _join_fragments(items: list[dict[str, Any]]) -> str:
    return " ".join(str(item.get("content", "")).strip() for item in items if str(item.get("content", "")).strip())


def _normalize_title(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().strip("-:;. ")


def _is_heading_candidate(title: str) -> bool:
    lowered = title.lower()
    return bool(title and lowered not in {"contents", "table of contents"} and len(title) <= 220 and not title.isdigit())


def _infer_heading_level(title: str, explicit_level: Any) -> int:
    numbered = re.match(r"^(?:section\s+)?(\d+(?:\.\d+)*)\b", title, re.IGNORECASE)
    if numbered:
        return min(numbered.group(1).count(".") + 1, 6)
    appendix = re.match(r"^(?:appendix|附录)\s+[A-Z]", title, re.IGNORECASE)
    if appendix:
        return 1
    try:
        level = int(explicit_level or 1)
    except (TypeError, ValueError):
        level = 1
    return max(1, min(level, 6))


def _drop_document_title_heading(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(headings) < 2:
        return headings
    first, second = headings[0], headings[1]
    if first["page"] == second["page"] and first["level"] <= second["level"] and len(first["title"]) > 20:
        return headings[1:]
    return headings


def _extract_document_title(extracted_dir: Path) -> str | None:
    full_md = extracted_dir / "full.md"
    if full_md.exists():
        for line in full_md.read_text(encoding="utf-8", errors="ignore").splitlines()[:80]:
            cleaned = _normalize_title(line.lstrip("#").strip())
            if _is_heading_candidate(cleaned):
                return cleaned
    headings = _extract_headings(extracted_dir)
    return headings[0]["title"] if headings else None


def _build_structure_from_headings(headings: list[dict[str, Any]], page_count: int) -> list[dict[str, Any]]:
    ordered = sorted(headings, key=lambda item: (int(item.get("page", 1)), int(item.get("level", 1)), str(item.get("title", ""))))
    nodes: list[dict[str, Any]] = []
    for idx, item in enumerate(ordered):
        start_page = max(1, int(item.get("page") or 1))
        end_page = page_count
        for next_item in ordered[idx + 1 :]:
            if int(next_item.get("level", 1)) <= int(item.get("level", 1)):
                end_page = max(start_page, int(next_item.get("page") or start_page) - 1)
                break
        nodes.append(
            {
                "node_id": f"{idx + 1:04d}",
                "title": item["title"],
                "level": int(item.get("level", 1)),
                "start_index": start_page,
                "end_index": min(max(end_page, start_page), page_count),
                "summary": "",
                "nodes": [],
            }
        )
    return _nest_heading_nodes(nodes)


def _nest_heading_nodes(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for item in headings:
        node = {key: item[key] for key in ["node_id", "title", "start_index", "end_index", "summary", "nodes"]}
        level = int(item.get("level", 1))
        while stack and int(stack[-1]["level"]) >= level:
            stack.pop()
        if stack:
            stack[-1]["node"]["nodes"].append(node)
        else:
            roots.append(node)
        stack.append({"level": level, "node": node})
    return roots


def _find_first(root: Path, names: list[str]) -> str | None:
    for name in names:
        candidate = root / name
        if candidate.exists():
            return str(candidate)
    return None
