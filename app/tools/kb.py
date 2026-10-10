"""Knowledge base: Markdown chunks + OpenAI embeddings (numpy cosine). Falls back to BM25 keyword search."""
import hashlib
import json
import math
import re
from collections import Counter
from functools import lru_cache

import numpy as np

from .. import config

URL_RE = re.compile(r"https?://[^\s)\]>,]+")
TOKEN_RE = re.compile(r"[a-z0-9]+|[ऀ-ॿ]+")
# Normalise common spelling variants so keyword search works on Hinglish / transliterations.
SYNONYMS = {"amrit": "amrut", "shahi": "amrut", "snana": "snan", "nasik": "nashik", "trimbak": "trimbakeshwar",
            "tryambakeshwar": "trimbakeshwar", "kushavart": "kushavarta", "kushawart": "kushavarta",
            "panchvati": "panchavati", "dates": "date", "kab": "date", "tarikh": "date", "tarikhen": "date",
            "helplines": "helpline", "numbers": "number", "trains": "train", "buses": "bus", "stations": "station",
            "parking": "parking", "kho": "lost", "khoya": "lost", "missing": "lost", "hotels": "hotel",
            "अमृत": "amrut", "स्नान": "snan", "रामकुंड": "ramkund", "त्र्यंबकेश्वर": "trimbakeshwar",
            "कुशावर्त": "kushavarta", "पार्किंग": "parking", "हेल्पलाइन": "helpline", "तारीख": "date",
            "तारखा": "date", "तारीखें": "date", "ट्रेन": "train", "रेल्वे": "train", "रेलवे": "train",
            "बस": "bus", "विमानतळ": "airport", "एयरपोर्ट": "airport", "हरवले": "lost", "खो": "lost",
            "खोया": "lost", "हरवला": "lost", "हरवली": "lost"}
STOP = {"the", "a", "an", "is", "are", "of", "to", "in", "on", "for", "and", "or", "what", "when", "where",
        "how", "i", "me", "my", "hai", "kya", "ka", "ki", "ke", "se", "mein", "है", "क्या", "का", "की", "के",
        "में", "से", "आहे", "का", "कधी", "कुठे", "मी", "माझे"}


def tokenize(text: str) -> list[str]:
    toks = TOKEN_RE.findall((text or "").lower())
    return [SYNONYMS.get(t, t) for t in toks if t not in STOP]


def _split_file(path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    title = (re.search(r"^# (.+)$", text, re.M) or [None, path.stem])[1]
    as_of = (re.search(r"As of:\s*([0-9-]+)", text) or [None, ""])[1]
    file_urls = URL_RE.findall(text)
    chunks, cur_head, buf = [], title, []

    def flush():
        body = "\n".join(buf).strip()
        if len(body) > 40:
            for i in range(0, len(body), 1400):  # hard cap long sections
                part = body[i:i + 1600]
                urls = list(dict.fromkeys(URL_RE.findall(part))) or file_urls[:1]
                low = (cur_head + part[:200]).lower()
                trust = "unverified" if ("unverified" in cur_head.lower() or "do not use" in low
                                         or "wrong dates" in low) else "verified"
                chunks.append({"file": path.name, "title": title, "heading": cur_head, "as_of": as_of, "trust": trust,
                               "text": f"{title} — {cur_head}\n{part}", "sources": urls[:4]})

    for line in text.splitlines():
        if re.match(r"^#{2,3} ", line):
            flush()
            buf, cur_head = [], line.lstrip("#").strip()
        else:
            buf.append(line)
    flush()
    return chunks


def load_chunks() -> list[dict]:
    files = sorted(p for p in config.KNOWLEDGE_DIR.glob("*.md") if p.name != "SOURCES.md")
    return [c for p in files for c in _split_file(p)]


def kb_fingerprint() -> str:
    h = hashlib.sha1()
    for p in sorted(config.KNOWLEDGE_DIR.glob("*.md")):
        h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()


# ---------- BM25 keyword fallback ----------
class BM25:
    def __init__(self, docs: list[list[str]], k1=1.4, b=0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.avg = sum(map(len, docs)) / max(len(docs), 1)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, q: list[str]) -> list[float]:
        out = []
        for d, tf in zip(self.docs, self.tf):
            s = 0.0
            for t in q:
                if t in tf:
                    s += self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            out.append(s)
        return out


@lru_cache(maxsize=1)
def _keyword_index():
    chunks = load_chunks()
    return chunks, BM25([tokenize(c["text"]) for c in chunks])


# ---------- embeddings ----------
@lru_cache(maxsize=1)
def _vector_index():
    if not config.INDEX_PATH.exists():
        return None
    z = np.load(config.INDEX_PATH, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    if meta.get("fingerprint") != kb_fingerprint():
        return None  # stale: KB edited since build; fall back to keywords until rebuilt
    return meta["chunks"], z["vectors"]


def index_status() -> str:
    if not config.INDEX_PATH.exists():
        return "missing"
    return "ready" if _vector_index() else "stale"


def _embed(texts: list[str]) -> np.ndarray:
    from openai import OpenAI
    resp = OpenAI(api_key=config.openai_key()).embeddings.create(model=config.EMBED_MODEL, input=texts)
    v = np.array([d.embedding for d in resp.data], dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def build_index() -> int:
    chunks = load_chunks()
    vecs = np.concatenate([_embed([c["text"] for c in chunks[i:i + 64]]) for i in range(0, len(chunks), 64)])
    meta = {"fingerprint": kb_fingerprint(), "model": config.EMBED_MODEL, "chunks": chunks}
    np.savez(config.INDEX_PATH, vectors=vecs, meta=np.array(json.dumps(meta, ensure_ascii=False)))
    _vector_index.cache_clear()
    return len(chunks)


def search_kumbh_info(query: str, k: int = 4) -> dict:
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "Empty query."}
    method, ranked = "keyword", []
    vi = _vector_index() if config.has_key() else None
    if vi:
        try:
            chunks, vecs = vi
            qv = _embed([query])[0]
            sims = vecs @ qv
            # Light hybrid: add keyword signal so exact names/numbers rank well.
            kchunks, bm = _keyword_index()
            kw = np.array(bm.scores(tokenize(query)), dtype=np.float32)
            if len(kw) == len(sims) and kw.max() > 0:
                sims = sims + 0.15 * kw / kw.max()
            sims = sims - 0.08 * np.array([c.get("trust") == "unverified" for c in chunks], dtype=np.float32)
            order = np.argsort(-sims)[:k]
            ranked = [(float(sims[i]), chunks[i]) for i in order]
            method = "embeddings"
        except Exception:
            ranked = []
    if not ranked:
        chunks, bm = _keyword_index()
        sc = [x * (0.6 if c.get("trust") == "unverified" else 1.0) for x, c in zip(bm.scores(tokenize(query)), chunks)]
        order = sorted(range(len(sc)), key=lambda i: -sc[i])[:k]
        ranked = [(sc[i], chunks[i]) for i in order if sc[i] > 0]
    if not ranked:
        return {"ok": True, "found": False, "passages": [],
                "advice": "Not in knowledge base. Say you don't have verified info; give 112 for emergencies "
                          "and the official NTKMA portal divcomnashik.maharashtra.gov.in."}
    return {"ok": True, "found": True, "method": method,
            "rule": "Answer only from passages with trust=verified unless the caller asks about unconfirmed items; "
                    "if you use an unverified passage, say it is not officially confirmed.",
            "passages": [{"text": c["text"][:1200], "trust": c.get("trust", "verified"),
                          "sources": c["sources"], "as_of": c["as_of"],
                          "file": c["file"], "score": round(s, 3)} for s, c in ranked]}
