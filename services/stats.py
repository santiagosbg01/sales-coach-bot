"""
Shared stats helper for /score and /report.
Computes: Current Month, Last Month, Total (all time) per user.
Also: tag-level breakdown (best/worst topics).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict
from sqlalchemy import func
from models import SessionLocal, Attempt, Grade, Question, User, UserStatus, UserRole

COUNTRY_FLAG = {
    "mexico": "🇲🇽", "colombia": "🇨🇴", "chile": "🇨🇱", "peru": "🇵🇪", "all": "🌎",
}


def _period_stats(db, user_id: int, since: Optional[datetime], until: Optional[datetime]) -> dict:
    """Return sent/answered/expired/correct counts for a time window."""
    q = db.query(Attempt).filter(Attempt.user_id == user_id)
    if since:
        q = q.filter(Attempt.asked_at >= since)
    if until:
        q = q.filter(Attempt.asked_at < until)

    all_attempts = q.all()
    sent      = len(all_attempts)
    answered  = sum(1 for a in all_attempts if not a.is_skipped)
    expired   = sum(1 for a in all_attempts if a.is_skipped)

    correct_q = db.query(Grade).join(Attempt).filter(
        Attempt.user_id == user_id,
        Grade.score_0_5 >= 3,
    )
    if since:
        correct_q = correct_q.filter(Attempt.asked_at >= since)
    if until:
        correct_q = correct_q.filter(Attempt.asked_at < until)
    correct = correct_q.count()

    return {
        "sent":     sent,
        "answered": answered,
        "expired":  expired,
        "correct":  correct,
    }


def period_stats_bulk(
    db, user_ids: List[int], since: Optional[datetime], until: Optional[datetime]
) -> Dict[int, dict]:
    """Return sent/correct (total) per user for a list of user_ids in 2 queries. Used by /users list."""
    if not user_ids:
        return {}
    # Sent per user
    q = (
        db.query(Attempt.user_id, func.count(Attempt.id).label("sent"))
        .filter(Attempt.user_id.in_(user_ids))
    )
    if since:
        q = q.filter(Attempt.asked_at >= since)
    if until:
        q = q.filter(Attempt.asked_at < until)
    sent_rows = q.group_by(Attempt.user_id).all()
    sent_map = {r.user_id: r.sent for r in sent_rows}
    # Correct per user (score >= 3)
    correct_q = (
        db.query(Attempt.user_id, func.count(Grade.id).label("correct"))
        .join(Grade, Attempt.id == Grade.attempt_id)
        .filter(Attempt.user_id.in_(user_ids), Grade.score_0_5 >= 3)
    )
    if since:
        correct_q = correct_q.filter(Attempt.asked_at >= since)
    if until:
        correct_q = correct_q.filter(Attempt.asked_at < until)
    correct_rows = correct_q.group_by(Attempt.user_id).all()
    correct_map = {r.user_id: r.correct for r in correct_rows}
    result = {}
    for uid in user_ids:
        result[uid] = {
            "sent":     sent_map.get(uid, 0),
            "answered": sent_map.get(uid, 0),
            "expired":  0,
            "correct":  correct_map.get(uid, 0),
        }
    return result


def user_stats(user_id: int, db=None) -> dict:
    """
    Returns stats for three periods:
      - current_month
      - last_month
      - total
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    now = datetime.utcnow()   # naive UTC — must match DB storage

    # Current month boundaries
    cur_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Last month boundaries
    if cur_start.month == 1:
        last_start = cur_start.replace(year=cur_start.year - 1, month=12)
    else:
        last_start = cur_start.replace(month=cur_start.month - 1)
    last_end = cur_start

    try:
        return {
            "current_month": _period_stats(db, user_id, cur_start, None),
            "last_month":    _period_stats(db, user_id, last_start, last_end),
            "total":         _period_stats(db, user_id, None, None),
        }
    finally:
        if close_db:
            db.close()


def fmt(stats: dict) -> str:
    """Format a single period stats dict into a compact string."""
    s, a, c, e = stats["sent"], stats["answered"], stats["correct"], stats["expired"]
    ans_pct = f"{round(a/s*100)}%" if s else "—"
    cor_pct = f"{round(c/a*100)}%" if a else "—"
    return f"📤{s} 💬{a}({ans_pct}) ✅{c}({cor_pct}) ⏰{e}"


def tag_breakdown(user_id: int, db=None) -> dict:
    """
    Returns per-product, per-country, and per-topic performance for a user (all time).
    Uses the explicit product/country columns; falls back to tags for topics.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        attempts = (
            db.query(Attempt)
            .filter(Attempt.user_id == user_id, Attempt.is_skipped == False)
            .all()
        )

        by_product = defaultdict(lambda: {"answered": 0, "correct": 0})
        by_country = defaultdict(lambda: {"answered": 0, "correct": 0})
        by_topic   = defaultdict(lambda: {"answered": 0, "correct": 0})

        # Tags that are structural/bank identifiers — skip in topic breakdown.
        # These come from VALID_SERVICES + generic bank/category names.
        from models.user import VALID_SERVICES as _valid_services
        SKIP_TAGS = set(_valid_services) | {"initial_questions", "general"}

        for attempt in attempts:
            question = db.query(Question).filter(Question.id == attempt.question_id).first()
            if not question:
                continue

            is_correct = bool(attempt.grade and attempt.grade.score_0_5 >= 3)

            # Product
            product = (question.product or "general").lower()
            by_product[product]["answered"] += 1
            if is_correct:
                by_product[product]["correct"] += 1

            # Country
            country = (question.country or "all").lower()
            by_country[country]["answered"] += 1
            if is_correct:
                by_country[country]["correct"] += 1

            # Topic tags
            for tag in (question.tags or []):
                tag = tag.lower()
                if tag not in SKIP_TAGS:
                    by_topic[tag]["answered"] += 1
                    if is_correct:
                        by_topic[tag]["correct"] += 1

        for d in [by_product, by_country, by_topic]:
            for v in d.values():
                v["pct"] = round(v["correct"] / v["answered"] * 100) if v["answered"] else 0

        ranked = [
            (tag, v["pct"], v["answered"])
            for tag, v in by_topic.items()
            if v["answered"] >= 2
        ]
        ranked.sort(key=lambda x: x[1], reverse=True)

        return {
            "by_product": dict(by_product),
            "by_country": dict(by_country),
            "by_topic":   dict(by_topic),
            "best":       ranked[:3],
            "worst":      list(reversed(ranked))[:3],
        }

    finally:
        if close_db:
            db.close()


def format_tag_breakdown(breakdown: dict) -> str:
    """Format the breakdown into a Telegram-ready string."""
    lines = []

    if breakdown["by_product"]:
        lines.append("*📦 Por producto:*")
        for prod, v in sorted(breakdown["by_product"].items(), key=lambda x: -x[1]["pct"]):
            bar = _bar(v["pct"])
            lines.append(f"  `{prod}` {bar} {v['correct']}/{v['answered']} ({v['pct']}%)")

    if breakdown["by_country"]:
        lines.append("\n*🌎 Por país:*")
        for country, v in sorted(breakdown["by_country"].items(), key=lambda x: -x[1]["answered"]):
            flag  = COUNTRY_FLAG.get(country, "🌐")
            label = country.capitalize() if country != "all" else "Todos los países"
            lines.append(f"  {flag} {label}: {v['correct']}/{v['answered']} ({v['pct']}%)")

    if breakdown["best"]:
        lines.append("\n*🏆 Mejores temas:*")
        for tag, pct, n in breakdown["best"]:
            lines.append(f"  ✅ `{tag}` — {pct}% ({n} resp.)")

    if breakdown["worst"]:
        lines.append("\n*⚠️ Temas a reforzar:*")
        for tag, pct, n in breakdown["worst"]:
            lines.append(f"  ❌ `{tag}` — {pct}% ({n} resp.)")

    if not lines:
        return "_Sin datos suficientes aún (mín. 2 respuestas por tema)_"

    return "\n".join(lines)


def _bar(pct: int) -> str:
    filled = round(pct / 10)
    return "█" * filled + "░" * (10 - filled)


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize to naive UTC (matches Attempt.asked_at in DB)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _avg_score_period(db, user_id: int, since_n, until_n) -> Optional[float]:
    q = (
        db.query(func.avg(Grade.score_0_5))
        .join(Attempt, Grade.attempt_id == Attempt.id)
        .filter(
            Attempt.user_id == user_id,
            Attempt.is_skipped == False,
            Grade.score_0_5.isnot(None),
        )
    )
    if since_n is not None:
        q = q.filter(Attempt.asked_at >= since_n)
    if until_n is not None:
        q = q.filter(Attempt.asked_at < until_n)
    v = q.scalar()
    if v is None:
        return None
    return round(float(v), 2)


def _graded_incorrect_count(db, user_id: int, since_n, until_n) -> int:
    q = (
        db.query(func.count(Grade.id))
        .join(Attempt, Grade.attempt_id == Attempt.id)
        .filter(
            Attempt.user_id == user_id,
            Attempt.is_skipped == False,
            Grade.score_0_5.isnot(None),
            Grade.score_0_5 < 3,
        )
    )
    if since_n is not None:
        q = q.filter(Attempt.asked_at >= since_n)
    if until_n is not None:
        q = q.filter(Attempt.asked_at < until_n)
    return int(q.scalar() or 0)


def period_answer_detail(db, user_id: int, since: Optional[datetime], until: Optional[datetime]) -> dict:
    """Counts + avg score (0–5) for a window; pass since=until=None for all-time."""
    since_n = _naive_utc(since) if since else None
    until_n = _naive_utc(until) if until else None
    base = _period_stats(db, user_id, since_n, until_n)
    inc = _graded_incorrect_count(db, user_id, since_n, until_n)
    avg = _avg_score_period(db, user_id, since_n, until_n)
    return {**base, "incorrect": inc, "avg_score": avg}


def _fmt_avg(avg: Optional[float]) -> str:
    return f"{avg}/5" if avg is not None else "—"


def format_rep_weekly_summary(user: User, since: datetime, until: datetime, db) -> str:
    """Telegram message: previous week correct/incorrect + lifetime averages for one rep."""
    since_label = since.strftime("%d/%m")
    until_label = (until - timedelta(seconds=1)).strftime("%d/%m/%Y")
    w = period_answer_detail(db, user.id, since, until)
    life = period_answer_detail(db, user.id, None, None)
    lines = [
        f"📊 *Tu resumen semanal — {Config.APP_NAME}*",
        f"_Semana del {since_label} al {until_label}_",
        "━━━━━━━━━━━━━━━━━━",
        "*Esta semana:*",
        f"  ✅ Correctas: *{w['correct']}*",
        f"  ❌ Incorrectas: *{w['incorrect']}*",
        f"  💬 Respondidas: {w['answered']} · ⏰ Expiradas/sin contestar: {w['expired']}",
        f"  📈 Promedio (semana): *{_fmt_avg(w['avg_score'])}*",
        "",
        "*Acumulado (histórico):*",
        f"  ✅ Correctas: *{life['correct']}*",
        f"  ❌ Incorrectas: *{life['incorrect']}*",
        f"  💬 Total respondidas: {life['answered']}",
        f"  📈 *Promedio general acumulado:* *{_fmt_avg(life['avg_score'])}*",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "_Cada lunes por la mañana · Usa /preguntas para practicar_",
    ]
    return "\n".join(lines)


def _team_avg_score(db, user_ids: List[int], since_n, until_n) -> Optional[float]:
    if not user_ids:
        return None
    q = (
        db.query(func.avg(Grade.score_0_5))
        .join(Attempt, Grade.attempt_id == Attempt.id)
        .filter(
            Attempt.user_id.in_(user_ids),
            Attempt.is_skipped == False,
            Grade.score_0_5.isnot(None),
        )
    )
    if since_n is not None:
        q = q.filter(Attempt.asked_at >= since_n)
    if until_n is not None:
        q = q.filter(Attempt.asked_at < until_n)
    v = q.scalar()
    return round(float(v), 2) if v is not None else None


def _team_incorrect_count(db, user_ids: List[int], since_n, until_n) -> int:
    if not user_ids:
        return 0
    q = (
        db.query(func.count(Grade.id))
        .join(Attempt, Grade.attempt_id == Attempt.id)
        .filter(
            Attempt.user_id.in_(user_ids),
            Attempt.is_skipped == False,
            Grade.score_0_5.isnot(None),
            Grade.score_0_5 < 3,
        )
    )
    if since_n is not None:
        q = q.filter(Attempt.asked_at >= since_n)
    if until_n is not None:
        q = q.filter(Attempt.asked_at < until_n)
    return int(q.scalar() or 0)


def _aggregate_detail(db, user_ids: List[int], since: Optional[datetime], until: Optional[datetime]) -> dict:
    """Roll up period_answer_detail across many reps (exact team averages from SQL)."""
    if not user_ids:
        return {"sent": 0, "answered": 0, "correct": 0, "expired": 0, "incorrect": 0, "avg_score": None}
    since_n = _naive_utc(since) if since else None
    until_n = _naive_utc(until) if until else None
    acc = {"sent": 0, "answered": 0, "correct": 0, "expired": 0, "incorrect": 0, "avg_score": None}
    for uid in user_ids:
        d = _period_stats(db, uid, since_n, until_n)
        acc["sent"] += d["sent"]
        acc["answered"] += d["answered"]
        acc["correct"] += d["correct"]
        acc["expired"] += d["expired"]
    acc["incorrect"] = _team_incorrect_count(db, user_ids, since_n, until_n)
    acc["avg_score"] = _team_avg_score(db, user_ids, since_n, until_n)
    return acc


def weekly_manager_team_summary(group_id: int, since: datetime, until: datetime, db=None) -> str:
    """
    Weekly summary for a manager's group: week results + team accumulated totals.
    """
    from models import Group

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        group = db.query(Group).get(group_id)
        if not group:
            return ""
        gids = group.descendant_ids(db)
        users = (
            db.query(User)
            .filter(User.status == UserStatus.ACTIVE, User.role == UserRole.REP, User.group_id.in_(gids))
            .order_by(User.name)
            .all()
        )
        if not users:
            return ""

        since_label = since.strftime("%d/%m")
        until_label = (until - timedelta(seconds=1)).strftime("%d/%m/%Y")
        uids = [u.id for u in users]
        week = _aggregate_detail(db, uids, since, until)
        life = _aggregate_detail(db, uids, None, None)

        lines = [
            f"📊 *Resumen semanal — {group.name}*",
            f"_Semana del {since_label} al {until_label}_",
            "━━━━━━━━━━━━━━━━━━",
            "*Tu equipo esta semana:*",
            f"  ✅ Correctas: *{week['correct']}*",
            f"  ❌ Incorrectas: *{week['incorrect']}*",
            f"  💬 Respondidas: {week['answered']} · ⏰ Expiradas: {week['expired']}",
            f"  📈 Promedio (semana): *{_fmt_avg(week['avg_score'])}*",
            "",
            "*Acumulado del equipo (histórico):*",
            f"  ✅ Correctas: *{life['correct']}*",
            f"  ❌ Incorrectas: *{life['incorrect']}*",
            f"  💬 Total respondidas: {life['answered']}",
            f"  📈 *Promedio general acumulado:* *{_fmt_avg(life['avg_score'])}*",
            "",
            "*Por ejecutivo (semana | acumulado):*",
        ]
        for u in users:
            wu = period_answer_detail(db, u.id, since, until)
            lu = period_answer_detail(db, u.id, None, None)
            lines.append(
                f"  • *{u.name}* — ✅{wu['correct']} ❌{wu['incorrect']} "
                f"({_fmt_avg(wu['avg_score'])}) · acum ✅{lu['correct']} ❌{lu['incorrect']} "
                f"({_fmt_avg(lu['avg_score'])})"
            )
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━",
            "_Cada lunes · Más detalle en el dashboard_",
        ]
        return "\n".join(lines)
    finally:
        if close_db:
            db.close()


def weekly_admin_digest_chunks(since: datetime, until: datetime, db=None, max_len: int = 3800) -> List[str]:
    """
    Admin-only weekly digest: by country/root group and each rep under it, plus ungrouped reps.
    Split into Telegram-safe chunks.
    """
    from models import Group

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        rep_count = (
            db.query(User)
            .filter(User.status == UserStatus.ACTIVE, User.role == UserRole.REP)
            .count()
        )
        if rep_count == 0:
            return []

        since_label = since.strftime("%d/%m")
        until_label = (until - timedelta(seconds=1)).strftime("%d/%m/%Y")
        header = (
            f"📊 *RESUMEN ADMIN — {Config.APP_NAME}*\n"
            f"_Semana del {since_label} al {until_label}_\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        chunks: List[str] = []
        buf = header

        roots = db.query(Group).filter(Group.parent_group_id.is_(None)).order_by(Group.name).all()
        for group in roots:
            gids = group.descendant_ids(db)
            reps = (
                db.query(User)
                .filter(User.status == UserStatus.ACTIVE, User.role == UserRole.REP, User.group_id.in_(gids))
                .order_by(User.name)
                .all()
            )
            if not reps:
                continue
            uids = [r.id for r in reps]
            week = _aggregate_detail(db, uids, since, until)
            life = _aggregate_detail(db, uids, None, None)
            block = [
                f"\n*🏢 {group.name}*",
                f"_Equipo — semana:_ ✅{week['correct']} ❌{week['incorrect']} "
                f"💬{week['answered']} ⏰{week['expired']} · prom {_fmt_avg(week['avg_score'])}",
                f"_Equipo — acumulado:_ ✅{life['correct']} ❌{life['incorrect']} "
                f"💬{life['answered']} · prom {_fmt_avg(life['avg_score'])}",
                "*Ejecutivos:*",
            ]
            for r in reps:
                wu = period_answer_detail(db, r.id, since, until)
                lu = period_answer_detail(db, r.id, None, None)
                block.append(
                    f"  • *{r.name}* — sem: ✅{wu['correct']} ❌{wu['incorrect']} "
                    f"{_fmt_avg(wu['avg_score'])} · acum: ✅{lu['correct']} ❌{lu['incorrect']} "
                    f"{_fmt_avg(lu['avg_score'])}"
                )
            piece = "\n".join(block) + "\n"
            if len(buf) + len(piece) > max_len:
                chunks.append(buf)
                buf = "📊 *RESUMEN ADMIN (continúa)*\n" + piece
            else:
                buf += piece

        loose = (
            db.query(User)
            .filter(
                User.status == UserStatus.ACTIVE,
                User.role == UserRole.REP,
                User.group_id.is_(None),
            )
            .order_by(User.name)
            .all()
        )
        if loose:
            block = ["\n*👤 Sin grupo asignado*", "*Ejecutivos:*"]
            for r in loose:
                wu = period_answer_detail(db, r.id, since, until)
                lu = period_answer_detail(db, r.id, None, None)
                block.append(
                    f"  • *{r.name}* — sem: ✅{wu['correct']} ❌{wu['incorrect']} "
                    f"{_fmt_avg(wu['avg_score'])} · acum: ✅{lu['correct']} ❌{lu['incorrect']} "
                    f"{_fmt_avg(lu['avg_score'])}"
                )
            piece = "\n".join(block) + "\n"
            if len(buf) + len(piece) > max_len:
                chunks.append(buf)
                buf = header + piece
            else:
                buf += piece

        buf += "\n━━━━━━━━━━━━━━━━━━\n_Resumen automático semanal · Dashboard para detalle_\n"
        chunks.append(buf)
        return chunks
    finally:
        if close_db:
            db.close()


def daily_admin_activity_chunks(
    since: datetime,
    until: datetime,
    db=None,
    max_len: int = 3800,
) -> List[str]:
    """
    Admin daily digest for a specific day window:
    - how many questions were sent to the team, and to whom
    - how many were answered
    - how many were correct vs incorrect
    Returns Telegram-safe chunks.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        # Normalize to naive UTC to match DB storage for Attempt.asked_at
        since_n = _naive_utc(since)
        until_n = _naive_utc(until)

        users = (
            db.query(User)
            .filter(User.status == UserStatus.ACTIVE, User.role == UserRole.REP)
            .order_by(User.name)
            .all()
        )
        if not users:
            return []

        day_label = since.strftime("%d/%m/%Y")
        header = (
            f"📬 *RESUMEN DIARIO (Admin) — {Config.APP_NAME}*\n"
            f"_Día: {day_label}_\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        team_sent = 0
        team_answered = 0
        team_correct = 0
        team_incorrect = 0
        team_expired = 0

        lines = []
        for u in users:
            d = period_answer_detail(db, u.id, since_n, until_n)
            sent = int(d.get("sent", 0) or 0)
            answered = int(d.get("answered", 0) or 0)
            correct = int(d.get("correct", 0) or 0)
            incorrect = int(d.get("incorrect", 0) or 0)
            expired = int(d.get("expired", 0) or 0)

            # Only include reps who were actually sent something that day
            if sent <= 0:
                continue

            team_sent += sent
            team_answered += answered
            team_correct += correct
            team_incorrect += incorrect
            team_expired += expired

            lines.append(
                f"• *{u.name}*: 📤{sent}  💬{answered}  ✅{correct}  ❌{incorrect}"
                + (f"  ⏰{expired}" if expired else "")
            )

        if not lines:
            return []  # Nothing to report — skip sending

        summary = (
            "👥 *Equipo (total)*\n"
            f"  📤 Enviadas: *{team_sent}*\n"
            f"  💬 Respondidas: *{team_answered}*\n"
            f"  ✅ Correctas: *{team_correct}*\n"
            f"  ❌ Incorrectas: *{team_incorrect}*\n"
            + (f"  ⏰ Expiradas: *{team_expired}*\n" if team_expired else "")
            + "\n"
        )

        chunks: List[str] = []
        buf = header + summary + "*Por ejecutivo:*\n"
        for line in lines:
            piece = line + "\n"
            if len(buf) + len(piece) > max_len:
                chunks.append(buf)
                buf = "📬 *RESUMEN DIARIO (continúa)*\n" + piece
            else:
                buf += piece

        buf += "\n━━━━━━━━━━━━━━━━━━\n_Digest automático diario · Dashboard para detalle_\n"
        chunks.append(buf)
        return chunks
    finally:
        if close_db:
            db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Weekly team summary
# ─────────────────────────────────────────────────────────────────────────────

def tag_breakdown_period(user_id: int, since: datetime, until: datetime, db) -> dict:
    """Like tag_breakdown() but restricted to a specific date window."""
    attempts = (
        db.query(Attempt)
        .filter(
            Attempt.user_id == user_id,
            Attempt.is_skipped == False,
            Attempt.asked_at >= since,
            Attempt.asked_at < until,
        )
        .all()
    )

    by_product = defaultdict(lambda: {"answered": 0, "correct": 0})
    by_topic   = defaultdict(lambda: {"answered": 0, "correct": 0})

    from models.user import VALID_SERVICES as _valid_services
    SKIP_TAGS = set(_valid_services) | {"initial_questions", "general"}

    for attempt in attempts:
        question = db.query(Question).filter(Question.id == attempt.question_id).first()
        if not question:
            continue

        is_correct = bool(attempt.grade and attempt.grade.score_0_5 >= 3)

        product = (question.product or "general").lower()
        by_product[product]["answered"] += 1
        if is_correct:
            by_product[product]["correct"] += 1

        for tag in (question.tags or []):
            tag = tag.lower()
            if tag not in SKIP_TAGS:
                by_topic[tag]["answered"] += 1
                if is_correct:
                    by_topic[tag]["correct"] += 1

    for d in [by_product, by_topic]:
        for v in d.values():
            v["pct"] = round(v["correct"] / v["answered"] * 100) if v["answered"] else 0

    ranked = [
        (tag, v["pct"], v["answered"])
        for tag, v in by_topic.items()
        if v["answered"] >= 2
    ]
    ranked.sort(key=lambda x: x[1], reverse=True)

    return {
        "by_product": dict(by_product),
        "best":       ranked[:3],
        "worst":      list(reversed(ranked))[:3],
    }


def _weekly_summary_for_users(users: list, since: datetime, until: datetime, db, title: str) -> tuple:
    """Build weekly summary blocks for a list of users. Returns (team_totals_dict, body_str)."""
    team = {"sent": 0, "answered": 0, "correct": 0, "expired": 0}
    user_blocks = []
    for user in users:
        s = _period_stats(db, user.id, since, until)
        team["sent"]     += s["sent"]
        team["answered"] += s["answered"]
        team["correct"]  += s["correct"]
        team["expired"]  += s["expired"]

        ans_pct = f"{round(s['answered']/s['sent']*100)}%" if s["sent"] else "—"
        cor_pct = f"{round(s['correct']/s['answered']*100)}%" if s["answered"] else "—"

        _flag = {"mexico": "🇲🇽", "colombia": "🇨🇴", "chile": "🇨🇱", "peru": "🇵🇪"}
        role_label = {"hunter": "🎯 Hunter", "farmer": "🌱 Farmer"}.get(
            user.sales_role.value if user.sales_role else "", ""
        )
        country_str = (
            _flag.get(user.base_country or "", "🌎") + " " + (user.base_country or "").capitalize()
            if user.base_country else ""
        )
        profile = "  ".join(x for x in [role_label, country_str] if x)

        block = [f"\n👤 *{user.name}*"]
        if profile:
            block.append(f"  _{profile}_")
        block += [
            f"  💬 Respondidas: {s['answered']}/{s['sent']} ({ans_pct})",
            f"  ✅ Correctas:   {s['correct']}/{s['answered']} ({cor_pct})",
        ]
        if s["expired"]:
            block.append(f"  ⏰ Expiradas:   {s['expired']}")

        bd = tag_breakdown_period(user.id, since, until, db)
        if bd["by_product"]:
            block.append("  📦 *Por servicio:*")
            for prod, v in sorted(bd["by_product"].items(), key=lambda x: -x[1]["pct"]):
                bar = _bar(v["pct"])
                block.append(f"    `{prod}` {bar} {v['correct']}/{v['answered']} ({v['pct']}%)")

        if bd["worst"]:
            block.append("  ⚠️ *Temas a reforzar:*")
            for tag, pct, n in bd["worst"]:
                block.append(f"    ❌ `{tag}` — {pct}% ({n} resp.)")

        if bd["best"]:
            block.append("  🏆 *Temas dominados:*")
            for tag, pct, n in bd["best"]:
                block.append(f"    ✅ `{tag}` — {pct}% ({n} resp.)")

        user_blocks.append("\n".join(block))

    t_ans_pct = f"{round(team['answered']/team['sent']*100)}%" if team["sent"] else "—"
    t_cor_pct = f"{round(team['correct']/team['answered']*100)}%" if team["answered"] else "—"

    lines = [
        f"👥 *{title} ({len(users)} rep{'s' if len(users) != 1 else ''})*",
        f"  📤 Enviadas:    {team['sent']}",
        f"  💬 Respondidas: {team['answered']} ({t_ans_pct})",
        f"  ✅ Correctas:   {team['correct']} ({t_cor_pct})",
    ]
    if team["expired"]:
        lines.append(f"  ⏰ Expiradas:   {team['expired']}")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines += user_blocks
    return team, "\n".join(lines)


def weekly_group_summary(group_id: int, since: datetime, until: datetime, db=None) -> str:
    """
    Build a Telegram-ready weekly summary for a group's reps.
    For country groups, includes all users from descendant sub-groups.
    Sent to the group manager as the weekly knowledge check.
    """
    from models import User, UserStatus, Group

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        group = db.query(Group).get(group_id)
        if not group:
            return ""

        gids = group.descendant_ids(db)
        users = (
            db.query(User)
            .filter(User.status == UserStatus.ACTIVE, User.group_id.in_(gids))
            .all()
        ) if gids else []
        if not users:
            return ""

        since_label = since.strftime("%d/%m")
        until_label = (until - timedelta(seconds=1)).strftime("%d/%m/%Y")

        _, body = _weekly_summary_for_users(users, since, until, db, group.name.upper())
        lines = [
            f"📊 *RESUMEN SEMANAL — {group.name}*",
            f"_Semana del {since_label} al {until_label}_",
            "━━━━━━━━━━━━━━━━━━",
            body,
            "\n━━━━━━━━━━━━━━━━━━",
            "_Enviado automáticamente cada lunes · Dashboard para más detalle_",
        ]
        return "\n".join(lines)
    finally:
        if close_db:
            db.close()


def weekly_team_summary(since: datetime, until: datetime, db=None) -> str:
    """
    Build a Telegram-ready weekly summary message covering all active users.
    `since` and `until` are UTC-aware datetimes bounding the reporting week.
    """
    from models import User, UserStatus

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        users = (
            db.query(User)
            .filter(User.status == UserStatus.ACTIVE)
            .all()
        )

        since_label = since.strftime("%d/%m")
        until_label = (until - timedelta(seconds=1)).strftime("%d/%m/%Y")

        lines = [
            f"📊 *RESUMEN SEMANAL — {Config.APP_NAME}*",
            f"_Semana del {since_label} al {until_label}_",
            "━━━━━━━━━━━━━━━━━━",
        ]

        _, body = _weekly_summary_for_users(users, since, until, db, "EQUIPO")
        lines.append(body)
        lines += [
            "\n━━━━━━━━━━━━━━━━━━",
            "_Enviado automáticamente cada lunes · /report para historial completo_",
        ]

        return "\n".join(lines)

    finally:
        if close_db:
            db.close()
