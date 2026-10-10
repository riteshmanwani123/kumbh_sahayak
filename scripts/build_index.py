"""Build the embedding index for the knowledge base (needs OPENAI_API_KEY in .env).

Usage:  .venv/bin/python -m scripts.build_index
Re-run whenever you edit files in knowledge/ (the app falls back to keyword search if the index is stale).
"""
import sys
import time

from app import config
from app.tools import kb


def main() -> int:
    if not config.has_key():
        print("OPENAI_API_KEY is not set in .env — cannot build embeddings. Keyword search still works.")
        return 1
    t0 = time.time()
    n = kb.build_index()
    print(f"Indexed {n} chunks with {config.EMBED_MODEL} in {time.time() - t0:.1f}s -> {config.INDEX_PATH}")
    r = kb.search_kumbh_info("second amrut snan date")
    top = r["passages"][0]["text"].splitlines()[0] if r.get("found") else "(none)"
    print(f"Sanity query via {r.get('method')}: {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
