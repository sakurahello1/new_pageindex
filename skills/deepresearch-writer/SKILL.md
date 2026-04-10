---
name: deepresearch-writer
description: "Use when Codex needs to run an end-to-end deep research writing workflow: receive a research query, search literature, build a local PageIndex knowledge base from selected papers or PDFs, create a cited Markdown outline, delegate section drafting to subagents when the user explicitly permits or asks for delegation, review and revise section drafts, and produce final Markdown research artifacts."
---

# DeepResearch Writer

Use this skill to produce a source-backed research report as Markdown files.
Start with the bundled init script to create the run directory and empty KB,
then search and ingest sources as separate later steps.

This skill depends on `deepresearch-pageindex` for KB operations. Use the
PageIndex KB CLI documented there whenever initializing, searching, adding
documents, listing trees, or reading document sections.

## Bootstrap Script

Run this from the PageIndex project root:

```bash
python skills/deepresearch-writer/scripts/deepresearch_bootstrap.py --name "<research run name>"
```

Useful options:

```bash
python skills/deepresearch-writer/scripts/deepresearch_bootstrap.py --name "rag-survey" --query "multi-turn retrieval augmented generation"
python skills/deepresearch-writer/scripts/deepresearch_bootstrap.py --name "rag-survey" --run-root F:/DeepResearch/runs
python skills/deepresearch-writer/scripts/deepresearch_bootstrap.py --name "rag-survey" --pageindex-root F:/DeepResearch/pageindex/PageIndex-main
```

The script only creates the Markdown run directory, scaffolds the standard
research files, and initializes an empty KB. It does not search literature and
does not ingest PDFs; run search and `add` commands after init.

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
  notes/
```

Use stable slugs from the research query. Keep all intermediate notes and the
final report in Markdown. Do not store API keys or secrets.

## Workflow

1. Initialize the run:
   - Run `python skills/deepresearch-writer/scripts/deepresearch_bootstrap.py --name "<run name>"`.
   - If the query is already known, optionally pass `--query "<research query>"`; otherwise fill it in `00_query.md`.
2. Search sources:
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
   - The init script already runs `python deepresearch_kb.py --kb research_runs/<slug>/kb init`.
   - Treat these KB commands as the `deepresearch-pageindex` layer of the workflow.
   - For each selected PDF worth reading, run `add --name <short-name> --source <pdf-url-or-path>`.
   - Use short, stable document names. Prefer arXiv/OpenAlex PDF URLs when available.
5. Inspect source structure:
   - Run `list` and `tree` for each selected document.
   - Tree output shows both the PageIndex node ID and a short stable `section_id` as `[node_id|section_id]`.
   - Prefer `read --section-id <hash>` for precise extraction. Use `read --node` or `read --range` when section IDs are unavailable.
   - Store only relevant excerpts or concise notes in the section files; do not paste long copyrighted passages.
6. Draft `03_outline.md`:
   - Include title, thesis, intended audience, and section list.
   - For every section, include the KB document names and exact section IDs, node IDs, or page ranges it will cite.
   - Do not create an outline section without at least one supporting source reference.
7. Draft sections:
   - Use `04_delegation_plan.md` and the section stubs under `sections/`.
   - If the user explicitly asks for subagents/delegation/parallel work, delegate each section to a subagent with only its section brief, citation targets, and relevant excerpts.
   - If delegation is not explicitly allowed in the current conversation, draft sections locally.
   - Each section draft must cite sources using a compact form such as `[doc_name sec a1b2c3d4]`, `[doc_name node 0004]`, or `[doc_name pp. 11-12]`.
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
python deepresearch_kb.py --kb research_runs/<slug>/kb read --name paper-a --section-id a1b2c3d4 --range 11-12 --max-chars 4000
```

## Quality Bar

- Prefer primary sources and PDFs over secondary summaries.
- Use PageIndex reads for specific claims instead of relying only on search snippets.
- Keep citations attached to the sections that use them.
- If a search result is interesting but not ingested into the KB, mark it as background only.
- If source retrieval, MinerU, or PDF ingestion fails, record the failure in the run directory and continue with available sources only when the remaining evidence is adequate.
