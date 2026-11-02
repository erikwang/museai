"""
ProdGuard — Stage 3: runbook retrieval (the 'R' in RAG).

Pipeline position:

    runbook .md files --(this module)--> ranked sections --(tool)-->
    Observation in the scratchpad --> the model cites [runbook:...] ids

Retrieval here is KEYWORD scoring on purpose, zero dependencies:

  * Every production RAG stack is this shape — chunk, score, top-k,
    inject — whether the scorer is keywords (BM25) or vector cosine
    similarity over embeddings. Learn the shape with a scorer you can
    debug by eye; swap in embeddings later (they need a model call per
    chunk and a vector store, and their failures are silent: a slightly
    wrong section that *looks* plausible).
  * Keyword scoring is transparent: the score breakdown below tells you
    exactly why a section ranked first. When retrieval misbehaves in
    production, that transparency is what you debug with.

Chunking choice: one chunk per '## ' section. Sections are the unit a
human would quote from a runbook, and the unit the agent should cite —
hence the evidence id format: runbook:<doc>#<section-slug>.

Scoring (deliberately simple and explainable):
  * +3 for each distinct query token found in the section TITLE
    (titles are dense summaries — a title hit is a strong signal);
  * +1 per body occurrence of each query token, capped at 3 per token
    (so a long section cannot win by repeating one word forever);
  * sections scoring 0 are dropped — no match means 'no runbook
    guidance', and the tool says so instead of returning the least-bad
    section. Returning irrelevant text is how RAG poisons an answer.
"""
from __future__ import annotations

import re
from pathlib import Path

RUNBOOK_DIR = Path(__file__).parent / "data" / "runbooks"

_STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "in", "on", "is", "did", "do",
    "what", "why", "how", "service",  # 'service' appears in every query here
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower())
            if t not in _STOPWORDS and len(t) > 1]


def _slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def load_sections() -> list[dict]:
    """Parse every runbook .md into section chunks (cached by callers)."""
    sections: list[dict] = []
    for path in sorted(RUNBOOK_DIR.glob("*.md")):
        doc_id = path.stem
        doc_title = doc_id
        current: dict | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                doc_title = line[2:].strip()
            elif line.startswith("## "):
                if current:
                    sections.append(current)
                title = line[3:].strip()
                current = {
                    "id": f"{doc_id}#{_slug(title)}",
                    "doc": doc_title,
                    "title": title,
                    "body": "",
                }
            elif current is not None:
                current["body"] += line + "\n"
        if current:
            sections.append(current)
    for s in sections:
        s["body"] = s["body"].strip()
    return sections


_SECTIONS: list[dict] | None = None


def _all_sections() -> list[dict]:
    global _SECTIONS
    if _SECTIONS is None:
        _SECTIONS = load_sections()
    return _SECTIONS


def score_section(query_tokens: set[str], section: dict) -> int:
    """Explainable keyword score; see the module docstring for the rules."""
    title_tokens = set(_tokens(section["title"]))
    body_tokens = _tokens(section["body"])
    score = 3 * len(query_tokens & title_tokens)
    for tok in query_tokens:
        score += min(body_tokens.count(tok), 3)
    return score


def search_runbooks(query: str, top_k: int = 2) -> list[dict]:
    """Return up to top_k sections ranked for the query (score > 0 only)."""
    q = set(_tokens(query))
    if not q:
        return []
    scored = [(score_section(q, s), i, s)
              for i, s in enumerate(_all_sections())]
    hits = [(sc, s) for sc, _, s in sorted(
        scored, key=lambda t: (-t[0], t[1])) if sc > 0]
    return [dict(s, score=sc) for sc, s in hits[:top_k]]


def format_results(results: list[dict]) -> str:
    """Render ranked sections as a tool Observation with evidence ids."""
    if not results:
        return ("[evidence: none] No runbook section matched. Proceed on "
                "log/job/change evidence only; do not invent a procedure.")
    blocks = []
    for r in results:
        blocks.append(
            f"[evidence: runbook:{r['id']}] {r['doc']} — {r['title']} "
            f"(match score {r['score']}):\n{r['body']}"
        )
    return "\n\n".join(blocks)
