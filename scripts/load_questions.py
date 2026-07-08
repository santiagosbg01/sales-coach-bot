"""Load questions from a named question bank JSON file."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import json
from models import SessionLocal, QuestionCategory, DifficultyLevel, init_db
from services import QuestionBank


def load_bank(filepath: str, replace: bool = False):
    """
    Load questions from a JSON file.

    Args:
        filepath: Path to the JSON question bank file.
        replace:  If True, deactivate all existing questions from the same
                  bank (matched by tags) before loading. Default False.
    """
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        sys.exit(1)

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    bank_name = data.get("bank_name", os.path.splitext(os.path.basename(filepath))[0])
    description = data.get("description", "")
    questions = data.get("questions", [])

    print(f"\n📦 Question Bank: {bank_name}")
    if description:
        print(f"   {description}")
    print(f"   {len(questions)} questions to load\n")

    db = SessionLocal()
    init_db()
    qb = QuestionBank(db)

    if replace:
        from models import Question
        existing = db.query(Question).filter(
            Question.tags.contains(bank_name)
        ).all()
        for q in existing:
            q.active = False
        db.commit()
        print(f"   ♻️  Deactivated {len(existing)} existing questions from bank '{bank_name}'\n")

    loaded = 0
    errors = 0
    for i, q in enumerate(questions, 1):
        try:
            cat  = QuestionCategory[q['category'].upper()]
            diff = DifficultyLevel[q.get('difficulty', 'MEDIUM').upper()]

            # Always inject bank_name as first tag for easy identification
            tags = q.get('tags', [])
            if bank_name not in tags:
                tags = [bank_name] + tags

            qb.create_question(
                prompt=q['prompt'],
                category=cat,
                difficulty=diff,
                must_have_concepts=q.get('must_have_concepts', []),
                good_to_have_concepts=q.get('good_to_have_concepts', []),
                tags=tags,
                ideal_answer=q.get('ideal_answer'),
                reference_url=q.get('reference_url'),
                reference_snippet=q.get('reference_snippet'),
                followup_templates=q.get('followup_templates', []),
            )
            loaded += 1

            if i % 10 == 0:
                print(f"   ✅ {i}/{len(questions)} cargadas...")

        except Exception as e:
            errors += 1
            print(f"   ⚠️  Error en pregunta {i}: {e}")

    db.close()

    print(f"\n{'✅' if errors == 0 else '⚠️ '} Cargadas: {loaded}/{len(questions)}", end="")
    if errors:
        print(f"  |  Errores: {errors}")
    else:
        print()

    # Show final stats
    db2 = SessionLocal()
    qb2 = QuestionBank(db2)
    stats = qb2.get_question_stats()
    db2.close()

    print(f"\n📊 Estado del banco de preguntas:")
    print(f"   Total activas: {stats['total']}")
    print(f"   Por categoría: {stats['by_category']}")
    print(f"   Por dificultad: {stats['by_difficulty']}")


def list_banks():
    """List all available question bank files in the data directory."""
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
    if not files:
        print("No question bank files found in data/")
        return
    print("\n📚 Available question banks:")
    for f in sorted(files):
        path = os.path.join(data_dir, f)
        try:
            with open(path) as fp:
                d = json.load(fp)
            name  = d.get('bank_name', f)
            count = len(d.get('questions', []))
            desc  = d.get('description', '')
            print(f"   • {name:20s}  ({count:3d} questions)  {desc[:60]}")
        except Exception:
            print(f"   • {f}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python load_questions.py <json_file> [--replace]")
        print("       python load_questions.py --list")
        print("\nExamples:")
        print("  python load_questions.py ../data/question_banks/saas_example.json")
        print("  python load_questions.py ../data/question_banks/saas_example.json --replace")
        print("  python load_questions.py --list")
        sys.exit(0)

    if sys.argv[1] == "--list":
        list_banks()
        sys.exit(0)

    filepath = sys.argv[1]
    replace  = "--replace" in sys.argv

    load_bank(filepath, replace=replace)
