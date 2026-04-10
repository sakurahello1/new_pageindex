---
name: deepresearch-writer
description: "Use when Codex needs to run an end-to-end deep research writing workflow: receive a research query, search literature, build a local PageIndex knowledge base from selected papers or PDFs, create a cited Markdown outline, delegate section drafting to subagents when the user explicitly permits or asks for delegation, review and revise section drafts, and produce final Markdown research artifacts."
---

# DeepResearch Writer

Use this skill to produce a source-backed research report as Markdown files.
Start with the bundled bootstrap script, then use the PageIndex KB CLI from the
project root for deeper tree inspection and source extraction.

## Bootstrap Script

Run this from the PageIndex project root:

```bash
python skills/deepresearch-writer/scripts/deepresearch_bootstrap.py --query "<research query>"
```

Useful options:

```bash
python skills/deepresearch-writer/scripts/deepresearch_bootstrap.py --query "<research query>" --source arxiv --limit 10 --ingest-limit 3
python skills/deepresearch-writer/scripts/deepresearch_bootstrap.py --query "<research query>" --source openalex --from-date 2023-01-01 --no-ingest
python skills/deepresearch-writer/scripts/deepresearch_bootstrap.py --query "<research query>" --pageindex-root F:/DeepResearch/pageindex/PageIndex-main
```

The script creates the Markdown run directory, runs literature search, records
candidate sources, initializes the KB, ingests up to `--ingest-limit` PDF-backed
papers unless `--no-ingest` is passed, saves source trees, and creates outline,
review, and final-report templates.

## Output Files

Create a run directory under `research_runs/`:

```text
research_runs/<slug>/
  00_query.md
  01_search_results.md
  02_selected_sources.md
  03_outline.md
  04_delegation_plan.md
  sections/
    <section-slug>.md
  05_review_notes.md
  final.md
  kb/
```

Use stable slugs from the research query. Keep all intermediate notes and the
final report in Markdown. Do not store API keys or secrets.

## Workflow

1. Capture the query in `00_query.md`.
2. Search sources:
   - Prefer running `scripts/deepresearch_bootstrap.py` first. Continue manually only if the script fails or the task needs custom selection.
   - Start with `python deepresearch_kb.py search-lit --source all --query "<2-3 key terms>" --limit 10`.
   - If the user specifies `arxiv` or `openalex`, pass `--source`.
   - Default date range is already 2020 onward; pass `--from-date` or `--to-date` only when the user asks or the topic needs it.
   - For arXiv, use 2-3 keywords. If more terms are needed, run multiple short arXiv searches rather than one long query.
   - Save raw candidates and search commands in `01_search_results.md`.
3. Select sources:
   - Choose papers that are directly relevant, recent enough for the query, and available as PDFs when possible.
   - Record title, authors, date, URL/PDF URL, and why each source was selected in `02_selected_sources.md`.
   - If there are too few good sources, run another focused search before drafting.
4. Initialize and populate the KB:
   - `python deepresearch_kb.py --kb research_runs/<slug>/kb init`
   - For each selected PDF, run `add --name <short-name> --source <pdf-url-or-path>`.
   - Use short, stable document names. Prefer arXiv/OpenAlex PDF URLs when available.
5. Inspect source structure:
   - Run `list` and `tree` for each selected document.
   - Use `read --node` or `read --range` to extract the exact parts needed for the report.
   - Store only relevant excerpts or concise notes in the section files; do not paste long copyrighted passages.
6. Draft `03_outline.md`:
   - Include title, thesis, intended audience, and section list.
   - For every section, include the document names and node IDs or page ranges it will cite.
   - Do not create an outline section without at least one supporting source reference.
7. Draft sections:
   - Use `04_delegation_plan.md` and the section stubs under `sections/`.
   - If the user explicitly asks for subagents/delegation/parallel work, delegate each section to a subagent with only its section brief, citation targets, and relevant excerpts.
   - If delegation is not explicitly allowed in the current conversation, draft sections locally.
   - Each section draft must cite sources using a compact form such as `[doc_name node 0004]` or `[doc_name pp. 11-12]`.
   - Save each section as `sections/<section-slug>.md`.
8. Review and integrate:
   - Check every claim has support in `03_outline.md`, selected sources, or extracted KB content.
   - Resolve duplicated arguments, unsupported claims, citation drift, and inconsistent terminology.
   - Record edits and unresolved caveats in `05_review_notes.md`.
9. Produce `final.md`:
   - Include the final report, citations, and a source list.
   - Keep claims precise. Mark uncertainty explicitly when evidence is limited.
   - Do not include internal planning notes in the final report.

## CLI Reminders

Search literature:

```bash
python deepresearch_kb.py search-lit --query "retrieval augmented generation"
python deepresearch_kb.py search-lit --source arxiv --query "multi turn rag" --limit 10
python deepresearch_kb.py search-lit --source openalex --query "long term memory agents" --from-date 2023-01-01
```

Build and inspect a KB:

```bash
python deepresearch_kb.py --kb research_runs/<slug>/kb init
python deepresearch_kb.py --kb research_runs/<slug>/kb add --name paper-a --source https://arxiv.org/pdf/2510.24701
python deepresearch_kb.py --kb research_runs/<slug>/kb list
python deepresearch_kb.py --kb research_runs/<slug>/kb tree --name paper-a --max-depth 4 --max-nodes 120
python deepresearch_kb.py --kb research_runs/<slug>/kb read --name paper-a --node 0004 --range 11-12 --max-chars 4000
```

## Quality Bar

- Prefer primary sources and PDFs over secondary summaries.
- Use PageIndex reads for specific claims instead of relying only on search snippets.
- Keep citations attached to the sections that use them.
- If a search result is interesting but not ingested into the KB, mark it as background only.
- If source retrieval, MinerU, or PDF ingestion fails, record the failure in the run directory and continue with available sources only when the remaining evidence is adequate.
