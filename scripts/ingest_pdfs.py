#!/usr/bin/env python3
"""Ingest PDF datasheets/specs into the Chroma vector store.

Extracts text per page with pdfplumber, splits it into overlapping
word-based chunks, embeds each chunk with an Ollama embedding model
(default: nomic-embed-text), and upserts the results into a persistent
Chroma collection.

Usage:
    python scripts/ingest_pdfs.py
    python scripts/ingest_pdfs.py --data-dir data --persist-dir chroma_db
"""

import argparse
import sys
from pathlib import Path

import chromadb
import ollama
import pdfplumber

REPO_ROOT = Path(__file__).resolve().parent.parent


def extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                pages.append((page_num, text))
    return pages


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    step = max(chunk_size - overlap, 1)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_size])
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(words):
            break
    return chunks


def embed_batch(texts: list[str], model: str) -> list[list[float]]:
    response = ollama.embed(model=model, input=texts)
    return response.embeddings


def ingest_pdf(pdf_path: Path, collection, embed_model: str, chunk_size: int, overlap: int) -> int:
    pages = extract_pages(pdf_path)
    ids, documents, metadatas = [], [], []
    for page_num, text in pages:
        for chunk_idx, chunk in enumerate(chunk_text(text, chunk_size, overlap)):
            ids.append(f"{pdf_path.name}::p{page_num}::c{chunk_idx}")
            documents.append(chunk)
            metadatas.append({"source": pdf_path.name, "page": page_num})

    if not documents:
        return 0

    embeddings = embed_batch(documents, embed_model)
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    return len(documents)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--persist-dir", type=Path, default=REPO_ROOT / "chroma_db")
    parser.add_argument("--collection", default="datasheets")
    parser.add_argument("--embed-model", default="nomic-embed-text")
    parser.add_argument("--chunk-size", type=int, default=250, help="words per chunk")
    parser.add_argument("--chunk-overlap", type=int, default=40, help="overlapping words between chunks")
    args = parser.parse_args()

    pdf_paths = sorted(p.resolve() for p in args.data_dir.glob("*.pdf")) + sorted(
        p.resolve() for p in args.data_dir.glob("*.PDF")
    )
    pdf_paths = [p for p in pdf_paths if p.exists()]  # drop dangling symlinks
    if not pdf_paths:
        print(f"No PDFs found under {args.data_dir} (expected symlinks to the sibling data dir).", file=sys.stderr)
        sys.exit(1)

    client = chromadb.PersistentClient(path=str(args.persist_dir))
    collection = client.get_or_create_collection(name=args.collection)

    for pdf_path in pdf_paths:
        n_chunks = ingest_pdf(pdf_path, collection, args.embed_model, args.chunk_size, args.chunk_overlap)
        print(f"{pdf_path.name}: {n_chunks} chunks upserted")

    print(f"Collection '{args.collection}' now has {collection.count()} documents at {args.persist_dir}")


if __name__ == "__main__":
    main()
