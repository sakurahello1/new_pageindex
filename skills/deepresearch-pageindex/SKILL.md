---
name: deepresearch-pageindex
description: Use when managing a local DeepResearch knowledge base backed by PageIndex trees, including initializing a KB, adding named PDF/URL/Markdown/text/Word documents, listing documents, viewing a document tree, or reading one or more document sections by node or range.
---

# DeepResearch PageIndex

Use the bundled CLI from the PageIndex project root:

```bash
python deepresearch_kb.py --kb <kb_dir> <command> ...
```

## Commands

Initialize a knowledge base:

```bash
python deepresearch_kb.py --kb ./kb init
```

Add a document. Always pass a stable `--name`; later commands use it instead of paths:

```bash
python deepresearch_kb.py --kb ./kb add --name paper-a --source ./paper.pdf --model gpt-4o-2024-11-20
python deepresearch_kb.py --kb ./kb add --name remote-paper --source https://example.com/paper.pdf --model gpt-4o-2024-11-20
python deepresearch_kb.py --kb ./kb add --name notes --source ./notes.md
```

Supported inputs: PDF path, PDF URL, `.md`, `.markdown`, `.txt`, `.docx`, and `.doc` when local Microsoft Word automation is available.

List documents:

```bash
python deepresearch_kb.py --kb ./kb list
```

Show one document tree:

```bash
python deepresearch_kb.py --kb ./kb tree --name paper-a
```

Read parts from a document. `--node` and `--range` can be repeated in the same command:

```bash
python deepresearch_kb.py --kb ./kb read --name paper-a --node 0001 --node 0003 --range 5-7 --max-chars 6000
```

For PDFs, ranges are pages. For Markdown/text/Word-derived documents, ranges are line numbers.

## Notes

- PDF tree generation uses PageIndex. Detected paper PDFs try MinerU heading extraction first; detected Chinese patent PDFs use the patent section preprocessor.
- API keys are environment variables, not committed files: `CHATGPT_API_KEY`, optional `OPENAI_BASE_URL`, optional `MINERU_API_TOKEN`, optional `MINERU_API_BASE`, optional `MINERU_OUTPUT_DIR`.
- If a document name already exists, pass `--force` to replace it.
