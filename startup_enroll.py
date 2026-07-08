"""
Seeds the database at startup:
1. Loads all question banks from data/*.json
2. Enrolls users from data/enrolled_users.json
Safe to run multiple times — skips existing records.
"""
import json
import logging
import os
import sys
from pathlib import Path
from models import (
    SessionLocal, User, ChannelIdentity,
    UserRole, UserStatus, SalesRole,
    QuestionCategory, DifficultyLevel, QuestionType,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DATA_DIR  = Path(__file__).parent / "data"
USERS_FILE = DATA_DIR / "enrolled_users.json"


def seed_questions():
    """Load all question bank JSON files into the database (skips duplicates)."""
    from services import QuestionBank
    from models import Question

    db = SessionLocal()
    total_loaded = 0
    try:
        for f in sorted(DATA_DIR.glob("*.json")):
            if f.name == "enrolled_users.json":
                continue

            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)

            bank_name = data.get("bank_name") or data.get("bank") or f.stem
            questions  = data.get("questions", [])

            # Deactivate stale questions for this bank that are no longer in the JSON.
            # Using active=False instead of DELETE to avoid FK constraint violations
            # on attempts/grades that may already reference those questions.
            current_prompts = {q["prompt"] for q in questions}
            stale = (
                db.query(Question)
                .filter(Question.tags.contains([bank_name]))
                .filter(~Question.prompt.in_(current_prompts))
                .all()
            )
            if stale:
                for sq in stale:
                    sq.active = False
                db.commit()
                logger.info(f"  🗑  Bank '{bank_name}': deactivated {len(stale)} stale question(s)")

            qb = QuestionBank(db)
            loaded = updated = 0
            for q in questions:
                try:
                    raw_cat = q.get("category", "general").upper()
                    cat = (
                        QuestionCategory[raw_cat]
                        if raw_cat in QuestionCategory.__members__
                        else QuestionCategory.GENERAL
                    )
                    diff = DifficultyLevel[q.get("difficulty", "medium").upper()]
                    tags = q.get("tags", [])
                    if bank_name not in tags:
                        tags = [bank_name] + tags

                    raw_type = q.get("question_type", "open_ended").upper()
                    qtype = QuestionType[raw_type] if raw_type in QuestionType.__members__ else QuestionType.OPEN_ENDED

                    # Upsert: update new type fields on existing questions
                    existing_q = db.query(Question).filter(
                        Question.prompt == q["prompt"]
                    ).first()

                    product = q.get("product") or bank_name
                    country = q.get("country", "all")

                    # rubric_key_points → must_have_concepts + ideal_answer
                    kp = q.get("rubric_key_points") or []
                    must_have = q.get("must_have_concepts") or kp
                    ideal     = q.get("ideal_answer") or ("; ".join(kp) if kp else None)

                    if existing_q:
                        existing_q.question_type = qtype
                        existing_q.difficulty    = diff
                        existing_q.choices       = q.get("choices")
                        existing_q.correct_answer = q.get("correct_answer")
                        existing_q.tags    = tags
                        existing_q.product = product
                        existing_q.country = country
                        # Update rubric if it exists
                        if existing_q.rubric:
                            existing_q.rubric.must_have_concepts = must_have
                            if ideal:
                                existing_q.rubric.ideal_answer = ideal
                        updated += 1
                    else:
                        qb.create_question(
                            prompt=q["prompt"],
                            category=cat,
                            difficulty=diff,
                            tags=tags,
                            question_type=qtype,
                            choices=q.get("choices"),
                            correct_answer=q.get("correct_answer"),
                            product=product,
                            country=country,
                            must_have_concepts=must_have,
                            good_to_have_concepts=q.get("good_to_have_concepts", []),
                            ideal_answer=ideal,
                            followup_templates=q.get("followup_templates", []),
                        )
                        loaded += 1
                except Exception as e:
                    logger.warning(f"  ⚠️  Skipped question: {e}")
                    db.rollback()

            db.commit()
            total_loaded += loaded
            logger.info(f"  📦 Bank '{bank_name}': {loaded} new, {updated} updated")

        logger.info(f"✅ Questions seeded: {total_loaded} new questions loaded")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error seeding questions: {e}")
    finally:
        db.close()


def seed_enrolled_users():
    if not USERS_FILE.exists():
        logger.warning("No enrolled_users.json found, skipping enrollment seed")
        return

    with open(USERS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    users = data.get("users", [])
    if not users:
        return

    db = SessionLocal()
    enrolled = 0
    skipped = 0

    try:
        for u in users:
            tg_id = str(u.get("telegram_user_id") or u.get("chat_id", ""))
            name  = u.get("name", "Rep")
            email = u.get("email", f"tg_{tg_id}@example.com")

            # Skip if already enrolled
            existing = db.query(ChannelIdentity).filter(
                ChannelIdentity.telegram_user_id == tg_id
            ).first()

            if existing:
                # Update profile fields on existing users
                internal = db.query(User).filter(User.id == existing.user_id).first()
                if internal:
                    raw_sr = u.get("sales_role", "").upper()
                    if raw_sr in SalesRole.__members__:
                        internal.sales_role = SalesRole[raw_sr]
                    if u.get("base_country"):
                        internal.base_country = u["base_country"].lower()
                    if u.get("specializations"):
                        internal.specializations = [s.lower() for s in u["specializations"]]
                skipped += 1
                continue

            # Resolve sales_role
            raw_sr = u.get("sales_role", "").upper()
            sr = SalesRole[raw_sr] if raw_sr in SalesRole.__members__ else None

            # Create user
            user = User(
                name=name,
                email=email,
                role=UserRole.REP,
                status=UserStatus.ACTIVE,
                sales_role=sr,
                base_country=u.get("base_country", "").lower() or None,
                specializations=[s.lower() for s in u.get("specializations", [])],
            )
            db.add(user)
            db.flush()

            # Create channel identity
            identity = ChannelIdentity(
                user_id=user.id,
                channel="telegram",
                telegram_user_id=tg_id,
                telegram_chat_id=tg_id,
            )
            db.add(identity)
            enrolled += 1

        db.commit()
        logger.info(f"✅ Enrolled {enrolled} new user(s), {skipped} already existed")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error seeding users: {e}")
    finally:
        db.close()


def sync_enrolled_json(db: Session) -> None:
    """Rewrite enrolled_users.json to match the current DB state. Call after adding users."""
    try:
        users = db.query(User).all()
        entries = []
        for u in users:
            ident = db.query(ChannelIdentity).filter(ChannelIdentity.user_id == u.id).first()
            entries.append({
                "name": u.name,
                "email": u.email or "",
                "chat_id": ident.telegram_chat_id if ident else "",
                "telegram_user_id": ident.telegram_user_id if ident else "",
                "sales_role": u.sales_role.value if u.sales_role else "",
                "base_country": u.base_country or "",
                "specializations": u.specializations or [],
                "active": u.status == UserStatus.ACTIVE,
            })
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump({"users": entries}, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning(f"Could not sync enrolled_users.json: {exc}")
