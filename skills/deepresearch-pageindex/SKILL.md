---
name: deepresearch-pageindex
description: Use when managing a local DeepResearch knowledge base backed by PageIndex trees, including initializing a KB, adding named PDF/URL/Markdown/text/Word documents, listing documents, viewing a document tree, or reading one or more document sections by short section id, node, or range.
---

# DeepResearch PageIndex

Use the bundled CLI from this skill's `scripts/` directory. It includes
`deepresearch_kb.py`, the PageIndex runtime scripts, and the local `pageindex/`
package copy:

```bash
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py --kb <kb_dir> <command> ...
```

If running from an installed skill outside the repository, use that installed
skill path instead. If Python dependencies are missing, install them from
`scripts/requirements.txt`.

## Commands

Initialize a knowledge base:

```bash
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py --kb ./kb init
```

Initialize a named knowledge base under a parent directory:

```bash
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py --kb ./knowledge_bases init --name papers
```

This creates `./knowledge_bases/papers`; use `--kb ./knowledge_bases/papers` for later commands.

Add a document. Always pass a stable `--name`; later commands use it instead of paths:

```bash
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py --kb ./kb add --name paper-a --source ./paper.pdf --model gpt-4o-2024-11-20
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py --kb ./kb add --name remote-paper --source https://example.com/paper.pdf --model gpt-4o-2024-11-20
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py --kb ./kb add --name notes --source ./notes.md
```

Supported inputs: PDF path, PDF URL, `.md`, `.markdown`, `.txt`, `.docx`, and `.doc` when local Microsoft Word automation is available.

List documents:

```bash
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py --kb ./kb list
```

Show one document tree:

```bash
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py --kb ./kb tree --name paper-a
```

Read parts from a document. `--section-id`/`--sid`, `--node`, and `--range` can be repeated in the same command:

```bash
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py --kb ./kb read --name paper-a --section-id a1b2c3d4 --node 0003 --range 5-7 --max-chars 6000
```

For PDFs, ranges are pages. For Markdown/text/Word-derived documents, ranges are line numbers.
Tree output includes both the PageIndex node ID and a short stable section ID
as `[node_id|section_id]`. Prefer section IDs when an LLM needs to revisit exact
document sections across steps.

Search literature from arXiv and/or OpenAlex:

```bash
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py search-lit --query "retrieval augmented generation"
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py search-lit --source arxiv --query "multi turn rag" --limit 10
python skills/deepresearch-pageindex/scripts/deepresearch_kb.py search-lit --source openalex --query "long term memory agents" --from-date 2023-01-01
```

Search defaults: `--source all`, `--limit 10`, and `--from-date 2020-01-01`.
For arXiv, prefer 2-3 keywords; long `--source arxiv` queries are rejected with
a reminder, while `--source all` skips arXiv and still queries OpenAlex.

## Notes

- PDF tree generation uses PageIndex. Detected paper PDFs try MinerU heading extraction first; detected Chinese patent PDFs use the patent section preprocessor.
- API keys are environment variables, not committed files: `CHATGPT_API_KEY`, optional `OPENAI_BASE_URL`, optional `MINERU_API_TOKEN`, optional `MINERU_API_BASE`, optional `MINERU_OUTPUT_DIR`.
- If a document name already exists, pass `--force` to replace it.
