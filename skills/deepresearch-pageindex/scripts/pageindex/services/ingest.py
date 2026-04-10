from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from .literature_preprocessor import detect_standard_literature, prepare_literature_structure


DEFAULT_PAGEINDEX_FALLBACK_MODEL = os.getenv("PAGEINDEX_FALLBACK_MODEL", "openai/gpt-oss-120b:nitro")


@dataclass
class IngestSource:
    source_path: str
    source_type: str
    document_type: str
    subtype: str | None
    status: str
    version: str | None
    year: int | None
    is_standard_literature: bool = False
    literature_kind: str | None = None
    detection_reason: str | None = None


class IngestService:
    def __init__(
        self,
        repo_root: str | Path,
        workspace_root: str | Path,
        model_name: str = DEFAULT_PAGEINDEX_FALLBACK_MODEL,
        max_workers: int = 3,
    ) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.model_name = model_name
        self.max_workers = max_workers
        self.normalized_dir = self.workspace_root / "normalized"
        self.trees_dir = self.workspace_root / "trees"
        self.state_dir = self.workspace_root / "state"
        for path in [self.normalized_dir, self.trees_dir, self.state_dir]:
            path.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / "ingest_state.json"
        self.state = self._load_state()

    def build_inventory(self, roots: list[str | Path]) -> list[IngestSource]:
        sources: list[IngestSource] = []
        for root in roots:
            root_path = Path(root).expanduser().resolve()
            if not root_path.exists():
                continue
            if root_path.is_file():
                if root_path.suffix.lower() in {".pdf", ".md", ".markdown"} and not root_path.name.startswith("~$"):
                    sources.append(self._classify_source(root_path))
                continue
            for path in root_path.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".pdf", ".md", ".markdown"} and not path.name.startswith("~$"):
                    sources.append(self._classify_source(path))
        return sources

    def ingest_sources(self, sources: list[IngestSource], force: bool = False) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for source in sources:
            record = self._process_source(source, force=force)
            if record is not None:
                records.append(record)
        return records

    def ingest_path(self, path: str | Path, force: bool = False) -> dict[str, Any]:
        source = self._classify_source(Path(path).expanduser().resolve())
        record = self._process_source(source, force=force)
        if record is None:
            raise RuntimeError(f"Failed to ingest {path}")
        return record

    def _classify_source(self, path: Path) -> IngestSource:
        detection = detect_standard_literature(path)
        suffix = path.suffix.lower().lstrip(".")
        year_match = re.search(r"(20\d{2})", str(path))
        document_type = "webpage" if suffix in {"md", "markdown"} else "document"
        subtype = None
        if detection.literature_kind == "paper":
            document_type = "paper"
            subtype = "academic_paper"
        elif detection.literature_kind == "patent":
            document_type = "patent"
            subtype = "patent"
        return IngestSource(
            source_path=str(path),
            source_type="md" if suffix == "markdown" else suffix,
            document_type=document_type,
            subtype=subtype,
            status="final",
            version=None,
            year=int(year_match.group(1)) if year_match else None,
            is_standard_literature=detection.is_standard_literature,
            literature_kind=detection.literature_kind,
            detection_reason=detection.reason,
        )

    def _process_source(self, source: IngestSource, force: bool) -> dict[str, Any] | None:
        parser_strategy = self._resolve_parser_strategy(source)
        state_key = f"{source.source_path}::{parser_strategy}"
        state_entry = self.state.get(state_key, {})
        if state_entry.get("status") == "done" and not force and Path(state_entry.get("structure_path", "")).exists():
            return dict(state_entry)

        normalized_content = self._normalize_source(source)
        structure_path, metadata = self._generate_tree(normalized_content, source, parser_strategy=parser_strategy)
        record = {
            "status": "done",
            "source_path": source.source_path,
            "content_path": str(normalized_content),
            "structure_path": str(structure_path),
            "document_type": source.document_type,
            "subtype": source.subtype,
            "year": source.year,
            "parser_strategy": parser_strategy,
            "metadata": metadata,
        }
        self.state[state_key] = record
        self._save_state()
        return record

    def _normalize_source(self, source: IngestSource) -> Path:
        src = Path(source.source_path)
        digest = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:12]
        out_path = self.normalized_dir / f"{digest}_{src.name}"
        if out_path.exists():
            return out_path
        shutil.copy2(src, out_path)
        return out_path

    def _generate_tree(self, content_path: Path, source: IngestSource, parser_strategy: str) -> tuple[Path, dict[str, Any]]:
        tree_path = self.trees_dir / f"{content_path.stem}_structure.json"
        metadata: dict[str, Any] = {
            "is_standard_literature": source.is_standard_literature,
            "literature_kind": source.literature_kind,
            "detection_reason": source.detection_reason,
        }

        if parser_strategy == "standard_literature" and source.is_standard_literature:
            parsed = prepare_literature_structure(
                pdf_path=content_path,
                structure_path=tree_path,
                source_pdf_path=source.source_path,
                cache_root=os.getenv("MINERU_OUTPUT_DIR") or str(self.workspace_root / "mineru_outputs"),
            )
            if parsed is not None:
                return parsed.structure_path, {**metadata, **parsed.metadata}
            metadata["fallback_reason"] = "literature_preprocess_unavailable"

        if content_path.suffix.lower() in {".md", ".markdown"}:
            self._run_pageindex(["python", "run_pageindex.py", "--md_path", str(content_path), "--model", self.model_name])
        else:
            self._run_pageindex(["python", "run_pageindex.py", "--pdf_path", str(content_path), "--model", self.model_name])

        generated = self.repo_root / "results" / f"{content_path.stem}_structure.json"
        if not generated.exists():
            raise FileNotFoundError(f"Tree generation did not produce {generated}")
        tree_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(generated, tree_path)
        return tree_path, {**metadata, "tree_generation_strategy": "pageindex_llm"}

    def _run_pageindex(self, cmd: list[str]) -> None:
        env = os.environ.copy()
        if "OPENROUTER_API_KEY" in env and "CHATGPT_API_KEY" not in env:
            env["CHATGPT_API_KEY"] = env["OPENROUTER_API_KEY"]
        if "OPENROUTER_BASE_URL" in env and "OPENAI_BASE_URL" not in env:
            env["OPENAI_BASE_URL"] = env["OPENROUTER_BASE_URL"]
        subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            env=env,
            timeout=1800,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def _resolve_parser_strategy(self, source: IngestSource) -> str:
        if source.document_type in {"paper", "patent"} and source.is_standard_literature and source.source_type == "pdf":
            return "standard_literature"
        return "pageindex"

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {}

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_single_node_pdf_structure(source_path: str | Path, structure_path: str | Path, title: str | None = None) -> Path:
    source = Path(source_path).expanduser().resolve()
    target = Path(structure_path).expanduser().resolve()
    if source.suffix.lower() in {".md", ".markdown"}:
        line_count = max(1, len(source.read_text(encoding="utf-8", errors="ignore").splitlines()))
        end_index = line_count
    else:
        with pymupdf.open(source) as pdf:
            end_index = max(1, pdf.page_count)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "doc_name": title or source.stem,
                "structure": [
                    {
                        "node_id": "root_0001",
                        "title": title or source.stem,
                        "start_index": 1,
                        "end_index": end_index,
                        "summary": "",
                        "nodes": [],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return target
