"""
Cleanup prompt prefixes like "(Supply Chain Manager)" or "[Abierta - ICP]"
so that questions read more como si un cliente potencial estuviera hablando
con el Hunter.

Heuristics (solo preguntas activas):
- If prompt startswith "(Supply Chain Manager) ...":
    "Imagina que un Supply Chain Manager te pregunta lo siguiente:\n<rest>"
- If prompt startswith "[Abierta - ICP] ...":
    "Imagina que un cliente potencial te dice:\n<rest>"

Run from project root:
  python scripts/cleanup_prompt_prefixes.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import SessionLocal, Question  # noqa: E402


SCM_PREFIX_RE = re.compile(r"^\s*\(Supply Chain Manager\)\s*", re.IGNORECASE)
ICP_PREFIX_RE = re.compile(r"^\s*\[Abierta\s*-\s*ICP\]\s*", re.IGNORECASE)


def transform_prompt(prompt: str) -> str:
    """Return transformed prompt if it matches any prefix; else original."""
    if not prompt:
        return prompt

    # (Supply Chain Manager) ...
    m_scm = SCM_PREFIX_RE.match(prompt)
    if m_scm:
        rest = prompt[m_scm.end() :].lstrip()
        return (
            "Imagina que un Supply Chain Manager te pregunta lo siguiente:\n"
            f"{rest}"
        )

    # [Abierta - ICP] ...
    m_icp = ICP_PREFIX_RE.match(prompt)
    if m_icp:
        rest = prompt[m_icp.end() :].lstrip()
        return (
            "Imagina que un cliente potencial te dice lo siguiente:\n"
            f"{rest}"
        )

    return prompt


def main() -> int:
    db = SessionLocal()
    updated = 0
    try:
        qs = db.query(Question).filter(Question.active == True).all()  # noqa: E712
        for q in qs:
            new_prompt = transform_prompt(q.prompt or "")
            if new_prompt != (q.prompt or ""):
                q.prompt = new_prompt
                updated += 1
        if updated:
            db.commit()
        print(f"✅ Cleanup complete. Updated {updated} question prompts.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

