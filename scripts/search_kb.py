"""Zero-dependency BM25 meme search over the local knowledge base.

Usage:
    python search_kb.py 绷不住
    python search_kb.py kskbl
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "memes.json"

_K1 = 1.5
_B = 0.3  # low length penalty: docs mix short summaries and long collection chunks
_BIGRAM_RE = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """Tokenize: Chinese chars as bigrams, latin/digits as lowercase words."""
    text = text.lower()
    tokens: list[str] = []
    for match in _BIGRAM_RE.finditer(text):
        pass  # handled below via sliding window
    # extract latin/number words
    for word in re.findall(r"[a-z0-9]+", text):
        tokens.append(word)
    # extract chinese bigrams
    chinese = "".join(_BIGRAM_RE.findall(text))
    for i in range(len(chinese) - 1):
        tokens.append(chinese[i : i + 2])
    if len(chinese) == 1:
        tokens.append(chinese)
    return tokens


class BM25Index:
    def __init__(self, docs: list[tuple[str, str, str]]) -> None:
        """docs: [(title, text, source)]"""
        self.docs = docs
        self.tokenized = [tokenize(title + " " + text) for title, text, _ in docs]
        self.doc_freqs: dict[str, int] = {}
        self.doc_lens: list[int] = []
        self.avgdl = 0.0
        for tokens in self.tokenized:
            self.doc_lens.append(len(tokens))
            for tok in set(tokens):
                self.doc_freqs[tok] = self.doc_freqs.get(tok, 0) + 1
        if self.doc_lens:
            self.avgdl = sum(self.doc_lens) / len(self.doc_lens)
        self.n = len(docs)

    def score(self, query_tokens: list[str], doc_idx: int) -> float:
        score = 0.0
        tokens = self.tokenized[doc_idx]
        dl = self.doc_lens[doc_idx]
        for tok in query_tokens:
            tf = tokens.count(tok)
            if tf == 0:
                continue
            df = self.doc_freqs.get(tok, 0)
            idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            denom = tf + _K1 * (1 - _B + _B * dl / self.avgdl) if self.avgdl else tf
            score += idf * (tf * (_K1 + 1)) / denom
        return score

    def search(self, query: str, top_k: int = 3) -> list[tuple[float, str, str, str]]:
        qt = tokenize(query)
        if not qt:
            return []
        ranked = sorted(
            ((self.score(qt, i), *self.docs[i]) for i in range(self.n)),
            key=lambda x: x[0],
            reverse=True,
        )
        return [(s, t, txt, src) for s, t, txt, src in ranked if s > 0][:top_k]


def load_index() -> BM25Index:
    if not OUT.exists():
        print(f"knowledge base not found: {OUT}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(OUT.read_text(encoding="utf-8"))
    docs = [
        (entry["title"], entry.get("summary", ""), entry.get("source", ""))
        for entry in data.values()
    ]
    return BM25Index(docs)


def main() -> None:
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        print("usage: python search_kb.py <meme keyword>", file=sys.stderr)
        sys.exit(1)
    index = load_index()
    for score, title, summary, source in index.search(query):
        print(f"--- {title} (score={score:.3f}, src={source})")
        print(summary[:400])
        print()


if __name__ == "__main__":
    main()
