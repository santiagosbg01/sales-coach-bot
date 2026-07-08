"""
Repair questions that are marked MULTIPLE_CHOICE but have empty/missing choices.

These questions trap users: the bot shows "Responde con la letra (A, B, C…)"
but no options are rendered, and any answer is rejected with
"Por favor responde solo con la letra de tu opción:".

Strategy per broken question:

  1. If the prompt starts with "[Abierta" → reclassify as OPEN_ENDED.
  2. If the prompt embeds options like "A) … B) … C) …" → extract them into
     the structured `choices` field (keeping MULTIPLE_CHOICE).
  3. If the prompt is short and phrased as yes/no (`¿…?` with no option list)
     → reclassify as YES_NO.
  4. Anything else → keep MULTIPLE_CHOICE but deactivate so users don't get it
     in new sessions until an admin fixes the content.

Run from project root:

    python scripts/fix_malformed_mc.py            # dry run (default)
    python scripts/fix_malformed_mc.py --apply    # persist changes

Also exposes a helper reachable from other modules:

    from scripts.fix_malformed_mc import find_malformed_mc
"""

import os
import re
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import SessionLocal, Question, QuestionType  # noqa: E402


# Match sequences like "A) foo B) bar C) baz" (also accepts lowercase & ". ")
_OPTION_RE = re.compile(r"(?<![A-Za-z])([A-Ea-e])\s*[\)\.]\s+(.+?)(?=(?:\s+[A-Ea-e]\s*[\)\.]\s+)|$)", re.DOTALL)


def _is_open_label(prompt: str) -> bool:
    head = (prompt or "").lstrip()[:80].lower()
    return head.startswith("[abierta") or "spin problema" in head or "spin necesidad" in head


def _extract_choices(prompt: str):
    """Try to pull inline A)/B)/C)/D) options out of the prompt text.

    Returns (clean_prompt, [{'key','text'}, ...]) if ≥ 2 options were found,
    otherwise (None, None).
    """
    if not prompt:
        return None, None
    matches = list(_OPTION_RE.finditer(prompt))
    if len(matches) < 2:
        return None, None
    choices = []
    for m in matches:
        key = m.group(1).upper()
        text = m.group(2).strip().rstrip(".").strip()
        if not text:
            continue
        if any(c["key"] == key for c in choices):
            continue
        choices.append({"key": key, "text": text})
    if len(choices) < 2:
        return None, None
    clean_prompt = prompt[: matches[0].start()].rstrip(" :.-\n")
    return clean_prompt or prompt, choices


_WH_SPANISH = (
    "qué", "que", "cuál", "cual", "cuáles", "cuales",
    "cómo", "como", "cuándo", "cuando", "dónde", "donde",
    "quién", "quien", "por qué", "por que", "para qué", "para que",
    "cuánto", "cuanto", "cuánta", "cuanta", "cuántos", "cuantos", "cuántas", "cuantas",
)


def _looks_like_yes_no(prompt: str) -> bool:
    if not prompt:
        return False
    p = prompt.strip()
    if len(p) > 260 or not p.startswith("¿") or not p.rstrip().endswith("?"):
        return False
    # Anything starting with a wh-word in Spanish asks for an open answer, not yes/no.
    head = p[1:].lstrip().lower()
    for wh in _WH_SPANISH:
        if head.startswith(wh + " ") or head.startswith(wh + ","):
            return False
    return True


def find_malformed_mc(db):
    rows = db.query(Question).filter(Question.question_type == QuestionType.MULTIPLE_CHOICE).all()
    out = []
    for q in rows:
        ch = q.choices or []
        ok = (
            isinstance(ch, list)
            and len(ch) >= 2
            and all(isinstance(c, dict) and c.get("key") and c.get("text") for c in ch)
        )
        if not ok:
            out.append(q)
    return out


def classify(q):
    """Return (action, details) where action is one of:
    'to_open_ended', 'to_yes_no', 'extract_choices', 'deactivate'."""
    if _is_open_label(q.prompt):
        return "to_open_ended", None
    clean, choices = _extract_choices(q.prompt or "")
    if choices:
        return "extract_choices", (clean, choices)
    if _looks_like_yes_no(q.prompt):
        return "to_yes_no", None
    return "deactivate", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Persist changes. Default is a dry run.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        broken = find_malformed_mc(db)
        if not broken:
            print("No malformed MC questions found. Nothing to do.")
            return 0

        print(f"Found {len(broken)} malformed MC question(s):\n")
        plan = {"to_open_ended": [], "to_yes_no": [], "extract_choices": [], "deactivate": []}
        for q in broken:
            action, details = classify(q)
            plan[action].append((q, details))

        for action, items in plan.items():
            if not items:
                continue
            print(f"[{action}] — {len(items)}")
            for q, details in items:
                prompt_preview = (q.prompt or "").replace("\n", " ")[:120]
                print(f"  - Q{q.id} active={q.active} · {prompt_preview}…")
                if action == "extract_choices":
                    _, choices = details
                    print(f"      choices → {[c['key'] + ') ' + c['text'][:30] for c in choices]}")
            print()

        if not args.apply:
            print("Dry run — no changes saved. Re-run with --apply to persist.")
            return 0

        changed = 0
        for q, details in plan["to_open_ended"]:
            q.question_type = QuestionType.OPEN_ENDED
            q.choices = None
            changed += 1
        for q, details in plan["to_yes_no"]:
            q.question_type = QuestionType.YES_NO
            q.choices = None
            changed += 1
        for q, details in plan["extract_choices"]:
            clean, choices = details
            q.prompt = clean
            q.choices = choices
            changed += 1
        for q, details in plan["deactivate"]:
            q.active = False
            changed += 1

        db.commit()
        print(f"Applied changes to {changed} question(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
