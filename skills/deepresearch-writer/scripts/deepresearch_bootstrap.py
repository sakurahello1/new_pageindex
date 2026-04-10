#!/usr/bin/env python
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Initialize a DeepResearch Markdown run backed by an empty PageIndex KB.")
    parser.add_argument("--name", required=True, help="Research run and knowledge-base name.")
    parser.add_argument("--query", default="", help="Optional research query note. Literature search is not run during init.")
    parser.add_argument("--run-root", default="research_runs", help="Directory where research runs are stored.")
    parser.add_argument("--pageindex-root", default=None, help="PageIndex repo root or deepresearch-pageindex scripts directory. Defaults to sibling skill, cwd, or PAGEINDEX_ROOT.")
    args = parser.parse_args()

    kb_cli = _resolve_kb_cli(args.pageindex_root)
    slug = _slugify(args.name)
    run_dir = Path(args.run_root).expanduser().resolve() / slug
    sections_dir = run_dir / "sections"
    trees_dir = run_dir / "source_trees"
    notes_dir = run_dir / "notes"
    kb_dir = run_dir / "kb"

    for path in [run_dir, sections_dir, trees_dir, notes_dir]:
        path.mkdir(parents=True, exist_ok=True)
    _run_checked([sys.executable, str(kb_cli), "--kb", str(kb_dir), "init"], cwd=kb_cli.parent)

    _write_text(
        run_dir / "00_query.md",
        "\n".join(
            [
                f"# {args.name}",
                "",
                f"- Created: {datetime.now(timezone.utc).isoformat()}",
                f"- KB: {kb_dir}",
                f"- Query: {args.query or 'TODO'}",
                "",
                "Add or refine the research query here before searching literature.",
                "",
            ]
        ),
    )
    _write_text(
        run_dir / "01_search_results.md",
        "\n".join(
            [
                "# Search Results",
                "",
                "Run literature search after init, then record commands and raw candidates here.",
                "",
                "```bash",
                f"python \"{kb_cli}\" search-lit --source all --query \"<2-3 key terms>\" --limit 10",
                "```",
                "",
            ]
        ),
    )
    _write_text(
        run_dir / "02_selected_sources.md",
        "\n".join(
            [
                "# Selected Sources",
                "",
                "Record selected sources after literature search. Ingest only sources worth reading into the KB.",
                "",
                "For each source, track:",
                "- KB document name: TODO",
                "- Title/authors/date: TODO",
                "- URL/PDF: TODO",
                "- Selection rationale: TODO",
                "",
            ]
        ),
    )
    _write_text(run_dir / "03_outline.md", _format_outline(args.query))
    _write_section_stubs(sections_dir, args.query)
    _write_text(run_dir / "04_delegation_plan.md", _format_delegation_plan())
    _write_text(run_dir / "05_review_notes.md", _format_review_notes())
    _write_text(run_dir / "final.md", _format_final_template(args.query))

    print(f"Created DeepResearch run: {run_dir}")
    print(f"KB: {kb_dir}")
    print(f"Query notes: {run_dir / '00_query.md'}")
    print(f"Outline: {run_dir / '03_outline.md'}")
    return 0


def _resolve_kb_cli(value: str | None) -> Path:
    candidates: list[Path] = []
    if value:
        base = Path(value).expanduser().resolve()
        candidates.extend([base / "deepresearch_kb.py", base / "scripts" / "deepresearch_kb.py"])
    env_root = __import__("os").environ.get("PAGEINDEX_ROOT")
    if env_root:
        base = Path(env_root).expanduser().resolve()
        candidates.extend([base / "deepresearch_kb.py", base / "scripts" / "deepresearch_kb.py"])
    script_path = Path(__file__).resolve()
    for parent in script_path.parents:
        candidates.extend(
            [
                parent / "deepresearch-pageindex" / "scripts" / "deepresearch_kb.py",
                parent / "skills" / "deepresearch-pageindex" / "scripts" / "deepresearch_kb.py",
                parent / "deepresearch_kb.py",
            ]
        )
    cwd = Path.cwd().resolve()
    candidates.extend(
        [
            cwd / "skills" / "deepresearch-pageindex" / "scripts" / "deepresearch_kb.py",
            cwd / "deepresearch_kb.py",
        ]
    )
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate
    raise SystemExit("Could not find deepresearch_kb.py. Install deepresearch-pageindex scripts, run from the PageIndex repo, or pass --pageindex-root.")


def _run_checked(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _format_outline(query: str) -> str:
    return "\n".join(
        [
            "# Cited Outline",
            "",
            "## Research Query",
            "",
            query or "TODO",
            "",
            "## Source Pool",
            "",
            "- TODO: add KB document names after selecting and ingesting sources",
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


def _write_section_stubs(sections_dir: Path, query: str) -> None:
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
                    f"Research query: {query or 'TODO'}",
                    "",
                    "## Required KB References",
                    "",
                    "- TODO: list document names and section IDs after ingestion",
                    "",
                    "## Draft",
                    "",
                    "TODO",
                    "",
                ]
            ),
        )


def _format_delegation_plan() -> str:
    return "\n".join(
        [
            "# Delegation Plan",
            "",
            "Use this file when the user explicitly permits subagents/delegation/parallel drafting.",
            "",
            "## Shared KB References",
            "",
            "- TODO: list ingested document names and section IDs from tree output",
            "",
            "## Section Assignments",
            "",
            "### Background and Motivation",
            "- File: `sections/01-background-and-motivation.md`",
            "- Task: explain the problem setting and why the topic matters.",
            "- Required references: TODO choose document names + section IDs, node IDs, or page ranges.",
            "",
            "### Main Findings",
            "- File: `sections/02-main-findings.md`",
            "- Task: synthesize the most important claims and findings.",
            "- Required references: TODO choose document names + section IDs, node IDs, or page ranges.",
            "",
            "### Methods and Evidence",
            "- File: `sections/03-methods-and-evidence.md`",
            "- Task: compare methods, evidence, datasets, and evaluation results.",
            "- Required references: TODO choose document names + section IDs, node IDs, or page ranges.",
            "",
            "### Limitations and Open Questions",
            "- File: `sections/04-limitations-and-open-questions.md`",
            "- Task: identify limitations, gaps, and unresolved questions.",
            "- Required references: TODO choose document names + section IDs, node IDs, or page ranges.",
            "",
        ]
    )


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
            f"Query: {query or 'TODO'}",
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
