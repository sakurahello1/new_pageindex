#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Bootstrap a DeepResearch Markdown run backed by PageIndex.")
    parser.add_argument("--query", required=True, help="Research question or topic.")
    parser.add_argument("--run-root", default="research_runs", help="Directory where research runs are stored.")
    parser.add_argument("--slug", default=None, help="Run slug. Defaults to a slug derived from --query.")
    parser.add_argument("--pageindex-root", default=None, help="Directory containing deepresearch_kb.py. Defaults to cwd or PAGEINDEX_ROOT.")
    parser.add_argument("--source", choices=["arxiv", "openalex", "all"], default="all", help="Literature source.")
    parser.add_argument("--limit", type=int, default=10, help="Search results per source.")
    parser.add_argument("--from-date", default="2020-01-01", help="Earliest publication date, YYYY-MM-DD.")
    parser.add_argument("--to-date", default=None, help="Latest publication date, YYYY-MM-DD.")
    parser.add_argument("--ingest-limit", type=int, default=0, help="Number of PDF results to ingest into the KB. Default 0 defers PDF ingestion.")
    parser.add_argument("--no-ingest", action="store_true", help="Deprecated compatibility flag; same as --ingest-limit 0.")
    args = parser.parse_args()

    pageindex_root = _resolve_pageindex_root(args.pageindex_root)
    kb_cli = pageindex_root / "deepresearch_kb.py"
    slug = args.slug or _slugify(args.query)
    run_dir = Path(args.run_root).expanduser().resolve() / slug
    sections_dir = run_dir / "sections"
    trees_dir = run_dir / "source_trees"
    kb_dir = run_dir / "kb"

    for path in [run_dir, sections_dir, trees_dir]:
        path.mkdir(parents=True, exist_ok=True)
    _run_checked([sys.executable, str(kb_cli), "--kb", str(kb_dir), "init"], cwd=pageindex_root)

    _write_text(
        run_dir / "00_query.md",
        "\n".join(
            [
                f"# Query: {args.query}",
                "",
                f"- Created: {datetime.now(timezone.utc).isoformat()}",
                f"- Source: {args.source}",
                f"- Limit: {args.limit}",
                f"- Date range: {args.from_date} to {args.to_date or 'today'}",
                f"- KB: {kb_dir}",
                f"- PDF ingestion limit: {0 if args.no_ingest else max(0, args.ingest_limit)}",
                "",
            ]
        ),
    )

    search_data = _run_search(kb_cli, args.query, args.source, args.limit, args.from_date, args.to_date)
    _write_text(run_dir / "01_search_results.md", _format_search_results(search_data))

    pdf_candidates = _select_candidates(search_data, limit=None)
    ingest_candidates = _select_candidates(search_data, limit=0 if args.no_ingest else max(0, args.ingest_limit))
    _write_text(run_dir / "02_selected_sources.md", _format_selected_sources(pdf_candidates, no_ingest=args.no_ingest, ingest_limit=max(0, args.ingest_limit)))

    ingested: list[dict[str, Any]] = []
    if ingest_candidates and not args.no_ingest:
        for idx, candidate in enumerate(ingest_candidates, start=1):
            doc_name = _slugify(candidate["title"])[:40] or f"paper-{idx}"
            doc_name = f"{idx:02d}-{doc_name}".strip("-")
            add_cmd = [
                sys.executable,
                str(kb_cli),
                "--kb",
                str(kb_dir),
                "add",
                "--name",
                doc_name,
                "--source",
                candidate["pdf_url"],
                "--force",
            ]
            record = {"doc_name": doc_name, "candidate": candidate, "status": "pending"}
            try:
                proc = _run_checked(add_cmd, cwd=pageindex_root)
                record["status"] = "ingested"
                record["add_stdout"] = proc.stdout
                tree = _run_checked(
                    [
                        sys.executable,
                        str(kb_cli),
                        "--kb",
                        str(kb_dir),
                        "tree",
                        "--name",
                        doc_name,
                        "--max-depth",
                        "5",
                        "--max-nodes",
                        "160",
                    ],
                    cwd=pageindex_root,
                )
                tree_path = trees_dir / f"{doc_name}.md"
                _write_text(tree_path, f"# Tree: {doc_name}\n\n```text\n{tree.stdout.strip()}\n```\n")
                record["tree_path"] = str(tree_path)
            except subprocess.CalledProcessError as exc:
                record["status"] = "failed"
                record["error"] = (exc.stderr or exc.stdout or str(exc)).strip()
            ingested.append(record)

    source_records = ingested or [{"candidate": c, "doc_name": "", "status": "candidate"} for c in pdf_candidates[: min(6, len(pdf_candidates))]]
    _write_text(run_dir / "03_outline.md", _format_outline(args.query, source_records))
    _write_section_stubs(sections_dir, args.query, source_records)
    _write_text(run_dir / "04_delegation_plan.md", _format_delegation_plan(source_records))
    _write_text(run_dir / "05_review_notes.md", _format_review_notes())
    _write_text(run_dir / "final.md", _format_final_template(args.query))

    print(f"Created DeepResearch run: {run_dir}")
    print(f"Search results: {run_dir / '01_search_results.md'}")
    print(f"Selected sources: {run_dir / '02_selected_sources.md'}")
    print(f"Outline: {run_dir / '03_outline.md'}")
    print(f"KB: {kb_dir}")
    return 0


def _resolve_pageindex_root(value: str | None) -> Path:
    candidates: list[Path] = []
    if value:
        candidates.append(Path(value).expanduser().resolve())
    env_root = __import__("os").environ.get("PAGEINDEX_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve())
    candidates.append(Path.cwd().resolve())
    for candidate in candidates:
        if (candidate / "deepresearch_kb.py").exists():
            return candidate
    raise SystemExit("Could not find deepresearch_kb.py. Run from the PageIndex repo or pass --pageindex-root.")


def _run_search(kb_cli: Path, query: str, source: str, limit: int, from_date: str, to_date: str | None) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(kb_cli),
        "search-lit",
        "--source",
        source,
        "--query",
        query,
        "--limit",
        str(limit),
        "--from-date",
        from_date,
        "--json",
    ]
    if to_date:
        cmd.extend(["--to-date", to_date])
    proc = _run_checked(cmd, cwd=kb_cli.parent)
    return json.loads(proc.stdout)


def _run_checked(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _select_candidates(search_data: dict[str, Any], *, limit: int | None) -> list[dict[str, Any]]:
    if limit is not None and limit <= 0:
        return []
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for source_name in ["arxiv", "openalex"]:
        for paper in search_data.get("results", {}).get(source_name, []):
            pdf_url = paper.get("pdf_url")
            if not pdf_url:
                continue
            key = (pdf_url or paper.get("url") or paper.get("title") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            selected.append(paper)
            if limit is not None and len(selected) >= limit:
                return selected
    return selected


def _format_search_results(data: dict[str, Any]) -> str:
    lines = [
        "# Search Results",
        "",
        f"- Query: {data.get('query', '')}",
        f"- Date range: {data.get('from_date', '')} to {data.get('to_date', '')}",
        "",
    ]
    warnings = data.get("warnings") or {}
    if warnings:
        lines.append("## Warnings")
        lines.extend(f"- {name}: {message}" for name, message in warnings.items())
        lines.append("")
    for source, papers in (data.get("results") or {}).items():
        lines.append(f"## {source}")
        if not papers:
            lines.append("- No results.")
            lines.append("")
            continue
        for idx, paper in enumerate(papers, start=1):
            lines.extend(
                [
                    f"### {idx}. {paper.get('title', 'Untitled')}",
                    f"- Date: {paper.get('published_date') or 'unknown'}",
                    f"- Authors: {', '.join((paper.get('authors') or [])[:8])}",
                    f"- URL: {paper.get('url') or ''}",
                    f"- PDF: {paper.get('pdf_url') or ''}",
                    "",
                ]
            )
    return "\n".join(lines)


def _format_selected_sources(candidates: list[dict[str, Any]], *, no_ingest: bool, ingest_limit: int) -> str:
    lines = ["# Selected Sources", ""]
    if no_ingest or ingest_limit <= 0:
        lines.extend(
            [
                "PDF ingestion is deferred for this run. The KB directory has been initialized; add documents later with `deepresearch_kb.py --kb <run>/kb add --name <doc-name> --source <pdf-url-or-path>`.",
                "",
            ]
        )
    else:
        lines.extend([f"The first {ingest_limit} PDF-backed candidate(s) will be ingested during bootstrap.", ""])
    if not candidates:
        lines.append("No PDF-backed candidates selected.")
        return "\n".join(lines)
    for idx, paper in enumerate(candidates, start=1):
        lines.extend(
            [
                f"## {idx}. {paper.get('title', 'Untitled')}",
                f"- Source: {paper.get('source')}",
                f"- Date: {paper.get('published_date') or 'unknown'}",
                f"- Authors: {', '.join((paper.get('authors') or [])[:8])}",
                f"- URL: {paper.get('url') or ''}",
                f"- PDF: {paper.get('pdf_url') or ''}",
                "- KB document name: TODO after ingestion",
                "- Selection rationale: TODO",
                "",
            ]
        )
    return "\n".join(lines)


def _format_outline(query: str, records: list[dict[str, Any]]) -> str:
    refs = []
    for idx, record in enumerate(records, start=1):
        candidate = record.get("candidate", {})
        label = record.get("doc_name") or f"candidate-{idx}"
        status = record.get("status") or "candidate"
        tree_note = f"; tree: `{record['tree_path']}`" if record.get("tree_path") else "; tree/section IDs: TODO after ingestion"
        refs.append(f"- {label}: {candidate.get('title', 'Untitled')} ({candidate.get('published_date') or 'unknown'}; {status}{tree_note})")
    ref_block = "\n".join(refs) if refs else "- TODO: add sources"
    return "\n".join(
        [
            "# Cited Outline",
            "",
            f"## Research Query",
            "",
            query,
            "",
            "## Source Pool",
            "",
            ref_block,
            "",
            "## Outline",
            "",
            "### 1. Background and Motivation",
            "- Purpose: TODO",
            "- Required KB references: TODO document names + section IDs, node IDs, or page ranges",
            "",
            "### 2. Main Findings",
            "- Purpose: TODO",
            "- Required KB references: TODO document names + section IDs, node IDs, or page ranges",
            "",
            "### 3. Methods and Evidence",
            "- Purpose: TODO",
            "- Required KB references: TODO document names + section IDs, node IDs, or page ranges",
            "",
            "### 4. Limitations and Open Questions",
            "- Purpose: TODO",
            "- Required KB references: TODO document names + section IDs, node IDs, or page ranges",
            "",
        ]
    )


def _write_section_stubs(sections_dir: Path, query: str, records: list[dict[str, Any]]) -> None:
    available_refs = _format_available_refs(records)
    sections = [
        ("01-background-and-motivation.md", "Background and Motivation"),
        ("02-main-findings.md", "Main Findings"),
        ("03-methods-and-evidence.md", "Methods and Evidence"),
        ("04-limitations-and-open-questions.md", "Limitations and Open Questions"),
    ]
    for filename, title in sections:
        _write_text(
            sections_dir / filename,
            "\n".join(
                [
                    f"# {title}",
                    "",
                    f"Research query: {query}",
                    "",
                    "## Required Source References",
                    "",
                    available_refs,
                    "",
                    "## Draft",
                    "",
                    "TODO",
                    "",
                ]
            ),
        )


def _format_delegation_plan(records: list[dict[str, Any]]) -> str:
    available_refs = _format_available_refs(records)
    return "\n".join(
        [
            "# Delegation Plan",
            "",
            "Use this file when the user explicitly permits subagents/delegation/parallel drafting.",
            "",
            "## Shared Source References",
            "",
            available_refs,
            "",
            "## Section Assignments",
            "",
            "### Background and Motivation",
            "- File: `sections/01-background-and-motivation.md`",
            "- Task: explain the problem setting and why the topic matters.",
            "- Required references: TODO choose document names + node IDs/page ranges.",
            "- Prefer section IDs from `tree` output when available.",
            "",
            "### Main Findings",
            "- File: `sections/02-main-findings.md`",
            "- Task: synthesize the most important claims and findings.",
            "- Required references: TODO choose document names + node IDs/page ranges.",
            "- Prefer section IDs from `tree` output when available.",
            "",
            "### Methods and Evidence",
            "- File: `sections/03-methods-and-evidence.md`",
            "- Task: compare methods, evidence, datasets, and evaluation results.",
            "- Required references: TODO choose document names + node IDs/page ranges.",
            "- Prefer section IDs from `tree` output when available.",
            "",
            "### Limitations and Open Questions",
            "- File: `sections/04-limitations-and-open-questions.md`",
            "- Task: identify limitations, gaps, and unresolved questions.",
            "- Required references: TODO choose document names + node IDs/page ranges.",
            "- Prefer section IDs from `tree` output when available.",
            "",
        ]
    )


def _format_available_refs(records: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, record in enumerate(records, start=1):
        candidate = record.get("candidate", {})
        doc_name = record.get("doc_name") or f"candidate-{idx}"
        status = record.get("status") or "unknown"
        lines.append(f"- `{doc_name}` ({status}): {candidate.get('title', 'Untitled')}")
        if record.get("tree_path"):
            lines.append(f"  - Tree: `{record['tree_path']}`")
        if candidate.get("pdf_url"):
            lines.append(f"  - PDF: {candidate['pdf_url']}")
    return "\n".join(lines) if lines else "- TODO: add sources"


def _format_review_notes() -> str:
    return "\n".join(
        [
            "# Review Notes",
            "",
            "- Unsupported claims found: TODO",
            "- Citation drift corrections: TODO",
            "- Terminology normalization: TODO",
            "- Remaining uncertainty: TODO",
            "",
        ]
    )


def _format_final_template(query: str) -> str:
    return "\n".join(
        [
            "# DeepResearch Report",
            "",
            f"Query: {query}",
            "",
            "## Executive Summary",
            "",
            "TODO",
            "",
            "## Findings",
            "",
            "TODO",
            "",
            "## Source List",
            "",
            "TODO",
            "",
        ]
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "deepresearch"


if __name__ == "__main__":
    raise SystemExit(main())
