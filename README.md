# PageIndex DeepResearch CLI

This repository keeps the PageIndex tree-generation core and adds a small
knowledge-base CLI for DeepResearch/Codex workflows.

It is intentionally scoped to:

- initialize a local knowledge base
- add a named document from a local path or PDF URL
- support PDF, Markdown, text, DOCX, and DOC inputs
- generate a PageIndex tree for each document
- list documents, print a document tree, and read one or more document parts
- handle paper and patent PDFs with a special preprocessing path before falling
  back to regular PageIndex generation

Cross-document search, research agents, old workspaces, generated examples,
caches, and test artifacts are not part of this trimmed project.

## Install

```bash
pip install -r requirements.txt
```

## Configuration

PageIndex defaults are read from:

```text
pageindex/config.yaml
```

LLM credentials are read from environment variables or a local `.env` file:

```bash
CHATGPT_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
```

`OPENAI_BASE_URL` is optional and can point to an OpenAI-compatible endpoint.
`OPENROUTER_API_KEY` and `OPENROUTER_BASE_URL` are also accepted by the ingest
wrapper and mapped to the PageIndex environment variables when present.

The paper preprocessing path can use MinerU when credentials are available:

```bash
MINERU_API_TOKEN=your_mineru_token_here
MINERU_API_BASE=https://mineru.net/api/v4
MINERU_OUTPUT_DIR=/path/to/mineru_outputs
```

If `MINERU_OUTPUT_DIR` already contains extracted MinerU output, it is reused.
Chinese patent PDFs use rule-based section detection first.

## Knowledge-Base CLI

Initialize a knowledge base:

```bash
python deepresearch_kb.py --kb ./kb init
```

Initialize a named knowledge base under a parent directory:

```bash
python deepresearch_kb.py --kb ./knowledge_bases init --name papers
```

This creates `./knowledge_bases/papers`. Use that path for later commands:

```bash
python deepresearch_kb.py --kb ./knowledge_bases/papers list
```

Add a named document:

```bash
python deepresearch_kb.py --kb ./kb add --name paper1 --source ./paper.pdf --model gpt-4o-2024-11-20
```

Add from a PDF URL:

```bash
python deepresearch_kb.py --kb ./kb add --name patent1 --source https://example.com/patent.pdf
```

List documents:

```bash
python deepresearch_kb.py --kb ./kb list
```

Print one document tree:

```bash
python deepresearch_kb.py --kb ./kb tree --name paper1
```

Read one or more parts:

```bash
python deepresearch_kb.py --kb ./kb read --name paper1 --node 0001 --node 0002
python deepresearch_kb.py --kb ./kb read --name paper1 --section-id a1b2c3d4
python deepresearch_kb.py --kb ./kb read --name paper1 --range 3-5 --range 12
```

For PDF inputs, ranges are page numbers. For Markdown/TXT/Word inputs, ranges
refer to line numbers in the normalized Markdown content.
Tree output includes both the PageIndex node ID and a short stable section ID
as `[node_id|section_id]`. Prefer `--section-id` or `--sid` when an LLM needs to
revisit exact document sections across steps.

Search literature from arXiv and OpenAlex:

```bash
python deepresearch_kb.py search-lit --query "retrieval augmented generation"
python deepresearch_kb.py search-lit --source arxiv --query "multi turn rag" --limit 10
python deepresearch_kb.py search-lit --source openalex --query "long term memory agents" --from-date 2023-01-01 --to-date 2026-04-10
```

`search-lit` defaults to `--source all`, `--limit 10`, and
`--from-date 2020-01-01`. For arXiv, use 2-3 keywords when possible; overly
long `--source arxiv` queries are rejected with a reminder to shorten the query.
When `--source all` is used, the CLI skips arXiv for overlong queries and still
queries OpenAlex.

## Direct PageIndex Usage

You can still call the PageIndex tree generator directly:

```bash
python run_pageindex.py --pdf_path ./document.pdf --model gpt-4o-2024-11-20
python run_pageindex.py --md_path ./document.md --model gpt-4o-2024-11-20
```

Output is written to:

```text
results/<document_name>_structure.json
```
