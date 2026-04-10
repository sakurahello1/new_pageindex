# PageIndex Minimal

This directory keeps only the local PageIndex core needed for:

- generating a tree structure from a PDF or Markdown file
- detecting paper/patent PDFs and using literature-specific preprocessing when possible
- reading source text back through a generated tree node or page range

Removed from this local copy: cookbooks, tutorials, tests, generated logs/results, old runtime workspaces, cross-document search, research-outline agents, semantic store code, and related caches.

## Install

```bash
pip install -r requirements.txt
```

## Configuration

Tree generation reads the default options from:

```text
pageindex/config.yaml
```

The model API credentials are read from environment variables. You can create a local `.env` file from `.env.example`:

```bash
CHATGPT_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
```

`OPENAI_BASE_URL` is optional and can point to any OpenAI-compatible endpoint, for example OpenRouter or a local Ollama-compatible server.

Literature preprocessing can also use MinerU when a paper PDF is detected. MinerU credentials are read from environment variables:

```bash
MINERU_API_TOKEN=your_mineru_token_here
MINERU_API_BASE=https://mineru.net/api/v4
MINERU_OUTPUT_DIR=/path/to/mineru_outputs
```

`MINERU_OUTPUT_DIR` is optional. If an extracted MinerU cache already exists there, it will be reused.

## Generate A Tree

For PDF:

```bash
python run_pageindex.py --pdf_path /path/to/document.pdf --model gpt-4o-2024-11-20
```

For Markdown:

```bash
python run_pageindex.py --md_path /path/to/document.md --model gpt-4o-2024-11-20
```

Output is written to:

```text
results/<document_name>_structure.json
```

## Read Source Text Through A Tree

Read one tree node:

```bash
python run_read_tree.py --source_path /path/to/document.pdf --structure_path results/document_structure.json --node_id 0006
```

Read a PDF page range:

```bash
python run_read_tree.py --source_path /path/to/document.pdf --structure_path results/document_structure.json --pages 3-5
```

For Markdown sources, node reading works the same way; direct ranges use line indexes from the tree.

## Literature Ingest

Use `run_ingest.py` when you want automatic paper/patent detection before falling back to PageIndex tree generation:

```bash
python run_ingest.py /path/to/papers_or_patents --workspace workspace --model gpt-4o-2024-11-20
```

Detected Chinese patent PDFs use rule-based outline extraction for sections such as `专利信息`, `摘要`, `权利要求书`, `技术领域`, `背景技术`, `发明内容`, `附图说明`, and `具体实施方式`. Detected paper PDFs try MinerU heading extraction first, then fall back to regular PageIndex generation.
