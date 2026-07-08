"""
Sweep all active questions and ensure multiple-choice / yes-no questions
have a correct_answer set when it can be inferred from existing text.

Heuristics:
- multiple_choice:
  - Look for patterns like "Correcta: A" or "Correcta: B)" in either
    rubric.ideal_answer or question.prompt.
  - Only set if the key exists in choices.
- yes_no:
  - Look for "Respuesta: Sí/Si" or "Respuesta: No" in rubric.ideal_answer
    or question.prompt, and set correct_answer to "si" or "no".

Run from project root:
  python scripts/fix_missing_correct_answers.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import SessionLocal, Question, QuestionType  # noqa: E402


MC_PATTERN = re.compile(r"correcta\s*:\s*([a-d])", re.IGNORECASE)
YN_SI_PATTERN = re.compile(r"respuesta\s*:\s*s[ií]\b", re.IGNORECASE)
YN_NO_PATTERN = re.compile(r"respuesta\s*:\s*no\b", re.IGNORECASE)


def _infer_mc_key(text: str):
    if not text:
        return None
    m = MC_PATTERN.search(text)
    if not m:
        return None
    return m.group(1).upper()


def _infer_yes_no(text: str):
    if not text:
        return None
    if YN_SI_PATTERN.search(text):
        return "si"
    if YN_NO_PATTERN.search(text):
        return "no"
    return None


def main() -> int:
    db = SessionLocal()
    fixed_mc = fixed_yn = 0
    checked_mc = checked_yn = 0

    try:
        qs = db.query(Question).filter(Question.active == True).all()  # noqa: E712
        for q in qs:
            qtype = q.question_type or QuestionType.OPEN_ENDED
            # Multiple choice
            if qtype == QuestionType.MULTIPLE_CHOICE:
                checked_mc += 1
                if q.correct_answer:
                    continue
                source_text = ""
                if q.rubric and q.rubric.ideal_answer:
                    source_text = q.rubric.ideal_answer
                elif q.correct_answer:
                    source_text = q.correct_answer
                else:
                    source_text = q.prompt or ""
                key = _infer_mc_key(source_text)
                if not key:
                    continue
                # Only accept if key exists in choices
                keys = {c.get("key", "").upper() for c in (q.choices or [])}
                if key not in keys:
                    continue
                q.correct_answer = key
                fixed_mc += 1

            # Yes/No
            elif qtype == QuestionType.YES_NO:
                checked_yn += 1
                if q.correct_answer:
                    continue
                source_text = ""
                if q.rubric and q.rubric.ideal_answer:
                    source_text = q.rubric.ideal_answer
                else:
                    source_text = q.prompt or ""
                val = _infer_yes_no(source_text)
                if not val:
                    continue
                q.correct_answer = val
                fixed_yn += 1

        db.commit()

        print("Sweep complete.")
        print(f"  Multiple choice checked: {checked_mc}, fixed: {fixed_mc}")
        print(f"  Yes/No checked:         {checked_yn}, fixed: {fixed_yn}")

    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

