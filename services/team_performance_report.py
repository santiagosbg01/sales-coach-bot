"""
Build structured team performance reports (WoW) for the dashboard / Reportes section.
Window: naive UTC datetimes, end exclusive (same convention as services.stats).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, time, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytz
from sqlalchemy import desc, func

from models import (
    User,
    UserRole,
    UserStatus,
    Group,
    Attempt,
    Grade,
    Question,
    QuestionCategory,
    Redemption,
    QuestionFeedback,
)
from services.stats import period_answer_detail, _aggregate_detail, _naive_utc

CST = pytz.timezone("America/Mexico_City")

_FLAG = {"mexico": "🇲🇽", "colombia": "🇨🇴", "chile": "🇨🇱", "peru": "🇵🇪"}

CAT_LABEL_ES = {
    QuestionCategory.DISCOVERY: "Descubrimiento",
    QuestionCategory.OBJECTIONS: "Objeciones",
    QuestionCategory.QUALIFICATION: "Calificación",
    QuestionCategory.CLOSING: "Cierre",
    QuestionCategory.VALUE_PROPOSITION: "Propuesta de valor",
    QuestionCategory.GENERAL: "General",
}


def _fmt_pct(num: int, den: int) -> int:
    return round(num / den * 100) if den else 0


def _wow_metrics(cur: dict, prev: dict) -> dict:
    out = {}
    for k in ("sent", "answered", "correct", "expired", "incorrect"):
        c, p = int(cur.get(k, 0) or 0), int(prev.get(k, 0) or 0)
        out[k] = {"current": c, "previous": p, "delta": c - p}
    ca, pa = cur.get("avg_score"), prev.get("avg_score")
    out["avg_score"] = {
        "current": ca,
        "previous": pa,
        "delta": (round(ca - pa, 2) if ca is not None and pa is not None else None),
    }
    c_cor = _fmt_pct(cur["correct"], cur["answered"])
    p_cor = _fmt_pct(prev["correct"], prev["answered"])
    out["accuracy_pct"] = {"current": c_cor, "previous": p_cor, "delta": c_cor - p_cor}
    return out


def last_completed_week_bounds_cst(now_cst: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """
    Return (period_start_cst, period_end_cst) for the last full Mon–Sun week in CST,
    as timezone-aware datetimes. Interval in UTC is [start, end) with end = Monday 00:00 CST.
    """
    now = now_cst or datetime.now(CST)
    if now.tzinfo is None:
        now = CST.localize(now)
    d = now.date()
    this_monday_date = d - timedelta(days=d.weekday())
    this_monday = CST.localize(datetime.combine(this_monday_date, time(0, 0, 0)))
    period_end = this_monday
    period_start = this_monday - timedelta(days=7)
    return period_start, period_end


def bounds_to_naive_utc(start_cst: datetime, end_cst: datetime) -> Tuple[datetime, datetime]:
    su = start_cst.astimezone(timezone.utc).replace(tzinfo=None)
    eu = end_cst.astimezone(timezone.utc).replace(tzinfo=None)
    return su, eu


def _active_reps(db) -> List[User]:
    return (
        db.query(User)
        .filter(User.status == UserStatus.ACTIVE, User.role == UserRole.REP)
        .order_by(User.name)
        .all()
    )


def _rep_label_country(u: User) -> str:
    c = (u.base_country or "").strip().lower()
    if not c:
        return "Sin país"
    return c.replace("_", " ").title()


def _rep_group_label(db, u: User) -> str:
    if not u.group_id:
        return "Sin grupo"
    g = db.query(Group).get(u.group_id)
    return g.name if g else f"Grupo #{u.group_id}"


def _top_wrong_questions(db, user_ids: List[int], since: datetime, until: datetime, limit: int = 12):
    if not user_ids:
        return []
    since_n, until_n = _naive_utc(since), _naive_utc(until)
    rows = (
        db.query(
            Question.id,
            Question.prompt,
            func.count(Attempt.id).label("n_wrong"),
        )
        .join(Attempt, Attempt.question_id == Question.id)
        .join(Grade, Grade.attempt_id == Attempt.id)
        .filter(
            Attempt.user_id.in_(user_ids),
            Attempt.is_skipped == False,
            Grade.score_0_5 < 3,
            Attempt.asked_at >= since_n,
            Attempt.asked_at < until_n,
        )
        .group_by(Question.id, Question.prompt)
        .order_by(desc("n_wrong"))
        .limit(limit)
        .all()
    )
    out = []
    for qid, prompt, n in rows:
        p = (prompt or "").replace("\n", " ").strip()
        if len(p) > 100:
            p = p[:97] + "…"
        out.append({"question_id": qid, "prompt": p, "wrong_count": int(n)})
    return out


def _vertical_breakdown(db, user_ids: List[int], since: datetime, until: datetime):
    """By product (vertical) and question category — current window only."""
    if not user_ids:
        return {"by_product": [], "by_category": []}
    since_n, until_n = _naive_utc(since), _naive_utc(until)
    by_prod = defaultdict(lambda: {"answered": 0, "correct": 0})
    by_cat = defaultdict(lambda: {"answered": 0, "correct": 0})

    attempts = (
        db.query(Attempt, Question)
        .join(Question, Question.id == Attempt.question_id)
        .filter(
            Attempt.user_id.in_(user_ids),
            Attempt.is_skipped == False,
            Attempt.asked_at >= since_n,
            Attempt.asked_at < until_n,
        )
        .all()
    )
    for att, q in attempts:
        ok = bool(att.grade and att.grade.score_0_5 is not None and att.grade.score_0_5 >= 3)
        prod = (q.product or "general").lower()
        by_prod[prod]["answered"] += 1
        if ok:
            by_prod[prod]["correct"] += 1
        cat = q.category
        ck = cat.value if cat else "general"
        by_cat[ck]["answered"] += 1
        if ok:
            by_cat[ck]["correct"] += 1

    prod_rows = []
    for prod, v in sorted(by_prod.items(), key=lambda x: -x[1]["answered"]):
        pct = _fmt_pct(v["correct"], v["answered"])
        prod_rows.append(
            {
                "key": prod,
                "label": prod.replace("_", " ").title(),
                "answered": v["answered"],
                "correct": v["correct"],
                "accuracy_pct": pct,
            }
        )
    cat_rows = []
    for ck, v in sorted(by_cat.items(), key=lambda x: -x[1]["answered"]):
        pct = _fmt_pct(v["correct"], v["answered"])
        try:
            enum_member = QuestionCategory(ck)
            label = CAT_LABEL_ES.get(enum_member, ck)
        except Exception:
            label = ck
        cat_rows.append(
            {
                "key": ck,
                "label": label,
                "answered": v["answered"],
                "correct": v["correct"],
                "accuracy_pct": pct,
            }
        )
    return {"by_product": prod_rows, "by_category": cat_rows}


def _vertical_wow(cur_rows: List[dict], prev_rows: List[dict]) -> List[dict]:
    prev_map = {r["key"]: r for r in (prev_rows or [])}
    out = []
    for r in cur_rows:
        p = prev_map.get(r["key"])
        out.append(
            {
                **r,
                "wow_accuracy_delta": (r["accuracy_pct"] - p["accuracy_pct"]) if p else None,
                "wow_answered_delta": (r["answered"] - p["answered"]) if p else None,
            }
        )
    return out


def _feedback_summary(db, since: datetime, until: datetime, limit: int = 12):
    since_n, until_n = _naive_utc(since), _naive_utc(until)
    q = (
        db.query(QuestionFeedback)
        .filter(
            QuestionFeedback.created_at >= since_n,
            QuestionFeedback.created_at < until_n,
        )
        .order_by(QuestionFeedback.created_at.desc())
    )
    total = q.count()
    items = q.limit(limit).all()
    lines = []
    for fb in items:
        u = db.query(User).get(fb.user_id)
        c = (fb.comment or "").replace("\n", " ").strip()
        if len(c) > 160:
            c = c[:157] + "…"
        lines.append(
            {
                "id": fb.id,
                "created_at": fb.created_at.isoformat() if fb.created_at else "",
                "user_name": u.name if u else str(fb.user_id),
                "comment": c,
                "handled": bool(fb.handled),
            }
        )
    return {"count": total, "samples": lines}


def _redemptions_summary(db, since: datetime, until: datetime):
    since_n, until_n = _naive_utc(since), _naive_utc(until)
    rows = (
        db.query(Redemption)
        .filter(Redemption.redeemed_at >= since_n, Redemption.redeemed_at < until_n)
        .all()
    )
    points = sum(int(r.points_spent or 0) for r in rows)
    by_prize: Dict[str, int] = defaultdict(int)
    for r in rows:
        pname = "—"
        if r.prize:
            pname = r.prize.name
        by_prize[pname] += 1
    by_prize_list = sorted(by_prize.items(), key=lambda x: -x[1])
    return {
        "count": len(rows),
        "points_spent": points,
        "by_prize": [{"name": k, "count": v} for k, v in by_prize_list[:15]],
    }


def _ranking_rows(reps: List[User]) -> List[dict]:
    ranked = sorted(reps, key=lambda u: (-int(u.points or 0), -int(u.streak_current or 0), u.name))
    out = []
    for i, u in enumerate(ranked, 1):
        out.append(
            {
                "user_id": u.id,
                "rank": i,
                "name": u.name,
                "points": int(u.points or 0),
                "streak": int(u.streak_current or 0),
                "country": _rep_label_country(u),
                "flag": _FLAG.get((u.base_country or "").lower(), "🌎"),
            }
        )
    return out


def _rank_delta_vs_previous(
    current_rows: List[dict], prev_payload: Optional[dict]
) -> List[dict]:
    old_ranks = {}
    if prev_payload and prev_payload.get("ranking"):
        for r in prev_payload["ranking"].get("rows", []):
            old_ranks[int(r["user_id"])] = int(r["rank"])
    out = []
    for r in current_rows:
        uid = int(r["user_id"])
        was = old_ranks.get(uid)
        now = int(r["rank"])
        out.append(
            {
                **r,
                "prev_rank": was,
                "rank_delta": (was - now) if was is not None else None,
            }
        )
    return out


def _auto_insights(
    team_wow: dict,
    by_country: List[dict],
    wrong_q: List[dict],
    inactive: List[dict],
    low_perf: List[dict],
) -> List[str]:
    lines = []
    acc = team_wow.get("accuracy_pct") or {}
    d = acc.get("delta")
    if d is not None and d != 0:
        lines.append(
            f"Precisión global {'subió' if d > 0 else 'bajó'} {abs(d)} pp vs la semana anterior."
        )
    sent_d = (team_wow.get("sent") or {}).get("delta")
    if sent_d is not None and sent_d != 0:
        lines.append(
            f"Volumen de preguntas enviadas al equipo {'creció' if sent_d > 0 else 'bajó'} en {abs(sent_d)} vs la semana previa."
        )
    for row in by_country[:4]:
        w = row.get("wow") or {}
        ad = (w.get("accuracy_pct") or {}).get("delta")
        if ad is not None and abs(ad) >= 8:
            lines.append(
                f"En {row['label']} la precisión {'mejoró' if ad > 0 else 'empeoró'} fuerte ({ad:+d} pp); conviene revisar coaching y banco."
            )
    if wrong_q:
        top = wrong_q[0]
        lines.append(
            f"Pregunta con más errores: #{top['question_id']} ({top['wrong_count']} incorrectas) — revisar guía o reforzar en equipo."
        )
    if len(inactive) >= 3:
        lines.append(
            f"{len(inactive)} ejecutivos sin respuestas en la semana; priorizar contacto o reactivación."
        )
    if len(low_perf) >= 2:
        lines.append("Hay varios perfiles con baja precisión pero actividad; sugerimos 1:1 sobre temas débiles.")
    if not lines:
        lines.append("Mantén el ritmo: no hay alertas fuertes respecto a la semana anterior.")
    return lines[:10]


def build_team_performance_report(
    db,
    period_start: datetime,
    period_end: datetime,
    prev_start: datetime,
    prev_end: datetime,
    prev_report_payload: Optional[dict] = None,
) -> dict:
    """
    Build full JSON payload for one report. All *_utc args are naive UTC, end exclusive.
    """
    reps = _active_reps(db)
    uids = [u.id for u in reps]

    cur_team = _aggregate_detail(db, uids, period_start, period_end)
    prev_team = _aggregate_detail(db, uids, prev_start, prev_end)
    team_wow = _wow_metrics(cur_team, prev_team)

    # By country (executive base_country)
    by_country_map: Dict[str, List[int]] = defaultdict(list)
    for u in reps:
        key = (u.base_country or "").lower() or "__none__"
        by_country_map[key].append(u.id)
    by_country = []
    for key, ids in sorted(by_country_map.items(), key=lambda x: -len(x[1])):
        label = "Sin país" if key == "__none__" else key.replace("_", " ").title()
        flag = _FLAG.get(key, "🌎") if key != "__none__" else "🌎"
        c_agg = _aggregate_detail(db, ids, period_start, period_end)
        p_agg = _aggregate_detail(db, ids, prev_start, prev_end)
        by_country.append(
            {
                "key": key,
                "label": label,
                "flag": flag,
                "reps": len(ids),
                "metrics": c_agg,
                "wow": _wow_metrics(c_agg, p_agg),
            }
        )

    # By team (group)
    by_group_map: Dict[str, List[int]] = defaultdict(list)
    for u in reps:
        gl = _rep_group_label(db, u)
        by_group_map[gl].append(u.id)
    by_team = []
    for gname, ids in sorted(by_group_map.items(), key=lambda x: -len(x[1])):
        c_agg = _aggregate_detail(db, ids, period_start, period_end)
        p_agg = _aggregate_detail(db, ids, prev_start, prev_end)
        by_team.append(
            {
                "group_name": gname,
                "reps": len(ids),
                "metrics": c_agg,
                "wow": _wow_metrics(c_agg, p_agg),
            }
        )

    # Per executive
    exec_rows = []
    scored = []
    for u in reps:
        c = period_answer_detail(db, u.id, period_start, period_end)
        p = period_answer_detail(db, u.id, prev_start, prev_end)
        cor_pct = _fmt_pct(c["correct"], c["answered"])
        prev_cor_pct = _fmt_pct(p["correct"], p["answered"])
        scored.append(
            (
                u,
                c,
                p,
                cor_pct,
                c["answered"],
            )
        )
        exec_rows.append(
            {
                "user_id": u.id,
                "name": u.name,
                "country": _rep_label_country(u),
                "flag": _FLAG.get((u.base_country or "").lower(), "🌎"),
                "group": _rep_group_label(db, u),
                "metrics": c,
                "wow": _wow_metrics(c, p),
                "accuracy_pct": cor_pct,
                "prev_accuracy_pct": prev_cor_pct,
            }
        )

    # Callouts
    active_scored = [t for t in scored if t[3] >= 3]  # answered >= 3
    by_accuracy = sorted(active_scored, key=lambda x: (-x[3], -x[4]))
    by_volume = sorted(scored, key=lambda x: (-x[2]["answered"], x[0].name))
    top_performers = [
        {"user_id": u.id, "name": u.name, "accuracy_pct": cor, "answered": ans}
        for u, _, _, cor, ans in by_accuracy[:5]
    ]
    most_active = [
        {"user_id": u.id, "name": u.name, "answered": c["answered"], "accuracy_pct": _fmt_pct(c["correct"], c["answered"])}
        for u, c, _, _, _ in sorted(scored, key=lambda x: (-x[1]["answered"], x[0].name))[:5]
    ]
    low_slice = list(reversed(by_accuracy))[:5]
    low_performers = [
        {"user_id": u.id, "name": u.name, "accuracy_pct": cor, "answered": ans}
        for u, _, _, cor, ans in low_slice
        if ans >= 3
    ]
    inactive = [
        {"user_id": u.id, "name": u.name, "answered": c["answered"], "sent": c["sent"]}
        for u, c, _, _, _ in scored
        if c["answered"] == 0
    ]

    wrong_cur = _top_wrong_questions(db, uids, period_start, period_end)
    wrong_prev = _top_wrong_questions(db, uids, prev_start, prev_end)

    vert_cur = _vertical_breakdown(db, uids, period_start, period_end)
    vert_prev = _vertical_breakdown(db, uids, prev_start, prev_end)
    by_product_wow = _vertical_wow(vert_cur["by_product"], vert_prev["by_product"])
    by_category_wow = _vertical_wow(vert_cur["by_category"], vert_prev["by_category"])

    fb_cur = _feedback_summary(db, period_start, period_end)
    fb_prev = _feedback_summary(db, prev_start, prev_end)

    red_cur = _redemptions_summary(db, period_start, period_end)
    red_prev = _redemptions_summary(db, prev_start, prev_end)

    ranking_rows = _ranking_rows(reps)
    ranking_with_delta = _rank_delta_vs_previous(ranking_rows, prev_report_payload)

    improvement_areas = []
    for row in by_category_wow:
        if row["answered"] >= 4 and row["accuracy_pct"] < 55:
            improvement_areas.append(
                {
                    "type": "category",
                    "label": row["label"],
                    "accuracy_pct": row["accuracy_pct"],
                    "answered": row["answered"],
                }
            )
    for row in by_product_wow:
        if row["answered"] >= 4 and row["accuracy_pct"] < 55:
            improvement_areas.append(
                {
                    "type": "product",
                    "label": row["label"],
                    "accuracy_pct": row["accuracy_pct"],
                    "answered": row["answered"],
                }
            )
    for w in wrong_cur[:5]:
        improvement_areas.append(
            {
                "type": "question",
                "label": w["prompt"],
                "question_id": w["question_id"],
                "wrong_count": w["wrong_count"],
            }
        )

    insights = _auto_insights(team_wow, by_country, wrong_cur, inactive, low_performers)

    ps_cst = period_start.replace(tzinfo=timezone.utc).astimezone(CST)
    pe_cst = period_end.replace(tzinfo=timezone.utc).astimezone(CST)
    period_label_es = (
        f"{ps_cst.strftime('%d/%m/%Y')} – {(pe_cst - timedelta(seconds=1)).strftime('%d/%m/%Y')} (CST)"
    )

    return {
        "meta": {
            "period_label_es": period_label_es,
            "period_start_utc": period_start.isoformat(),
            "period_end_utc": period_end.isoformat(),
            "prev_period_start_utc": prev_start.isoformat(),
            "prev_period_end_utc": prev_end.isoformat(),
            "generated_at_utc": datetime.utcnow().isoformat(),
        },
        "team": {"metrics": cur_team, "wow": team_wow},
        "by_country": by_country,
        "by_team": by_team,
        "executives": exec_rows,
        "improvement_areas": improvement_areas[:20],
        "insights": insights,
        "feedback": {
            "current": fb_cur,
            "previous_count": fb_prev["count"],
            "wow_count_delta": fb_cur["count"] - fb_prev["count"],
        },
        "knowledge_vertical": {
            "by_product": by_product_wow,
            "by_category": by_category_wow,
        },
        "common_errors": {"current": wrong_cur, "previous_top": wrong_prev[:5]},
        "callouts": {
            "top_performers": top_performers,
            "most_active": most_active,
            "low_performers": low_performers,
            "inactive_no_answers": inactive,
        },
        "redemptions": {
            "current": red_cur,
            "wow": {
                "count_delta": red_cur["count"] - red_prev["count"],
                "points_delta": red_cur["points_spent"] - red_prev["points_spent"],
            },
        },
        "ranking": {"rows": ranking_with_delta},
    }


def get_report_payload_for_period(db, period_start: datetime, period_end: datetime):
    """Return saved payload for an exact period, if any (for ranking WoW vs last file)."""
    from models import TeamReportSnapshot

    row = (
        db.query(TeamReportSnapshot)
        .filter(
            TeamReportSnapshot.period_start_utc == period_start,
            TeamReportSnapshot.period_end_utc == period_end,
        )
        .first()
    )
    return row.payload if row else None


def persist_report(db, period_start: datetime, period_end: datetime, payload: dict) -> Tuple[Any, bool]:
    """Insert snapshot if missing. Returns (row, created_new)."""
    from models import TeamReportSnapshot

    exists = (
        db.query(TeamReportSnapshot)
        .filter(
            TeamReportSnapshot.period_start_utc == period_start,
            TeamReportSnapshot.period_end_utc == period_end,
        )
        .first()
    )
    if exists:
        return exists, False
    snap = TeamReportSnapshot(
        period_start_utc=period_start,
        period_end_utc=period_end,
        payload=payload,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap, True
