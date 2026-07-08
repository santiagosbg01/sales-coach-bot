#!/usr/bin/env python3
"""
Prueba el correo del reporte semanal (SMTP).

  Borrador / vista previa (no envía, no requiere SMTP):
    python3 scripts/test_report_email.py dry-run
    python3 scripts/test_report_email.py dry-run --from-db

  Envío corto de prueba (verifica login SMTP y entrega):
    python3 scripts/test_report_email.py ping --to you@example.com

  Envía el HTML completo del último reporte guardado (una sola bandeja):
    python3 scripts/test_report_email.py full --to you@example.com

  O genera la última semana cerrada como el viernes y envía solo a --to:
    python3 scripts/test_report_email.py full --to you@example.com --generate

Variables de entorno: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
SMTP_USE_TLS, SMTP_USE_SSL, WEEKLY_REPORT_EMAIL_FROM, BASE_URL
"""
from __future__ import annotations

import argparse
import os
import sys

# Repo root on path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.chdir(_ROOT)


def _mask(s: str, keep: int = 3) -> str:
    if not s:
        return "(vacío)"
    if len(s) <= keep * 2:
        return "***"
    return s[:keep] + "…" + s[-keep:]


def cmd_dry_run(from_db: bool) -> int:
    from config import Config
    from services.report_email import render_weekly_report_html

    out_path = os.path.join(_ROOT, "report_email_preview.html")

    if from_db:
        from models import SessionLocal, TeamReportSnapshot, migrate_db
        from sqlalchemy import desc

        migrate_db()
        db = SessionLocal()
        try:
            snap = db.query(TeamReportSnapshot).order_by(desc(TeamReportSnapshot.id)).first()
            if not snap:
                print("No hay snapshots en la BD. Usa el dashboard «Generar última semana» o dry-run sin --from-db.")
                return 1
            payload = snap.payload or {}
            snap_id = snap.id
        finally:
            db.close()
    else:
        payload = {
            "meta": {
                "period_label_es": "Vista previa (datos de ejemplo)",
                "generated_at_utc": "—",
            },
            "team": {
                "metrics": {"sent": 10, "answered": 8, "correct": 5, "incorrect": 2, "expired": 2, "avg_score": 3.2},
                "wow": {
                    "sent": {"current": 10, "previous": 8, "delta": 2},
                    "answered": {"current": 8, "previous": 9, "delta": -1},
                    "correct": {"current": 5, "previous": 4, "delta": 1},
                    "incorrect": {"current": 2, "previous": 3, "delta": -1},
                    "expired": {"current": 2, "previous": 1, "delta": 1},
                    "avg_score": {"current": 3.2, "previous": 2.9, "delta": 0.3},
                    "accuracy_pct": {"current": 62, "previous": 55, "delta": 7},
                },
            },
            "insights": ["La precisión subió 7 pp vs la semana anterior (ejemplo)."],
            "callouts": {
                "top_performers": [{"name": "Ejemplo A", "accuracy_pct": 90, "answered": 5}],
                "most_active": [{"name": "Ejemplo B", "answered": 12, "accuracy_pct": 50}],
                "low_performers": [],
                "inactive_no_answers": [],
            },
            "by_country": [
                {
                    "flag": "🇲🇽",
                    "label": "Mexico",
                    "reps": 3,
                    "wow": {"accuracy_pct": {"current": 60, "previous": 55, "delta": 5}},
                }
            ],
            "by_team": [
                {"group_name": "Equipo demo", "reps": 3, "wow": {"accuracy_pct": {"current": 60, "delta": 5}}}
            ],
            "knowledge_vertical": {
                "by_product": [
                    {
                        "label": "Envios99",
                        "answered": 6,
                        "accuracy_pct": 66,
                        "wow_accuracy_delta": 4,
                    }
                ]
            },
            "common_errors": {"current": [{"question_id": 1, "prompt": "Pregunta de ejemplo", "wrong_count": 2}]},
            "improvement_areas": [{"type": "product", "label": "General", "accuracy_pct": 40, "answered": 5}],
            "feedback": {
                "current": {"count": 1, "samples": [{"created_at": "2026-01-01", "user_name": "Demo", "comment": "Comentario de prueba"}]},
                "previous_count": 0,
                "wow_count_delta": 1,
            },
            "redemptions": {"current": {"count": 0, "points_spent": 0}, "wow": {"count_delta": 0, "points_delta": 0}},
            "executives": [],
            "ranking": {"rows": []},
        }
        snap_id = 0

    base = (getattr(Config, "BASE_URL", "") or "").rstrip("/")
    report_url = f"{base}/reportes/{snap_id}" if snap_id else f"{base}/reportes"
    html = render_weekly_report_html(payload, snap_id, report_url)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print("Vista previa HTML guardada en:")
    print(" ", out_path)
    print("Ábrela en el navegador (es el mismo diseño que iría en el correo).")
    print()
    print("Estado SMTP (solo informativo):")
    print("  SMTP_HOST:     ", Config.SMTP_HOST or "(no definido — no se puede enviar)")
    print("  SMTP_PORT:     ", Config.SMTP_PORT)
    print("  SMTP_USER:     ", Config.SMTP_USER or "(no definido)")
    print("  SMTP_PASSWORD: ", _mask(Config.SMTP_PASSWORD))
    print("  FROM:          ", Config.WEEKLY_REPORT_EMAIL_FROM)
    return 0


def cmd_ping(to_addr: str) -> int:
    from config import Config
    from services.report_email import send_weekly_report_email

    if not (Config.SMTP_HOST or "").strip():
        print("Error: define SMTP_HOST (y usuario/contraseña) en .env")
        return 1

    app_name = getattr(Config, "APP_NAME", "Sales Coach")
    html = (
        "<!DOCTYPE html><html><body style='font-family:sans-serif;padding:24px;'>"
        f"<h1 style='color:#4f46e5;'>{app_name} — prueba SMTP</h1>"
        f"<p>Si lees esto, el envío desde <code>{Config.WEEKLY_REPORT_EMAIL_FROM}</code> funcionó.</p>"
        "<p style='color:#64748b;font-size:12px;'>Puedes borrar este mensaje.</p>"
        "</body></html>"
    )
    text = f"{app_name}: prueba SMTP OK.\n\nSi lees esto, el envío funcionó.\n"
    mail_from = (Config.WEEKLY_REPORT_EMAIL_FROM or "").strip()
    if not mail_from:
        print("ERROR: WEEKLY_REPORT_EMAIL_FROM no está configurado en .env")
        return 1
    send_weekly_report_email(
        html_body=html,
        text_body=text,
        subject=f"[PRUEBA {app_name}] SMTP OK",
        mail_from=mail_from,
        recipients=[to_addr.strip()],
    )
    print("Enviado a:", to_addr)
    return 0


def cmd_full(to_addr: str, generate: bool) -> int:
    from config import Config
    from models import SessionLocal, TeamReportSnapshot, migrate_db
    from sqlalchemy import desc
    from services.report_email import render_weekly_report_html, send_weekly_report_email, _plain_text_summary
    from datetime import timedelta

    migrate_db()
    db = SessionLocal()
    try:
        if generate:
            from services.team_performance_report import (
                last_completed_week_bounds_cst,
                bounds_to_naive_utc,
                build_team_performance_report,
                persist_report,
                get_report_payload_for_period,
            )

            p_start_cst, p_end_cst = last_completed_week_bounds_cst()
            period_start, period_end = bounds_to_naive_utc(p_start_cst, p_end_cst)
            prev_start_cst = p_start_cst - timedelta(days=7)
            prev_end_cst = p_start_cst
            prev_start, prev_end = bounds_to_naive_utc(prev_start_cst, prev_end_cst)
            prev_payload = get_report_payload_for_period(db, prev_start, prev_end)
            payload = build_team_performance_report(
                db, period_start, period_end, prev_start, prev_end, prev_payload
            )
            snap, _ = persist_report(db, period_start, period_end, payload)
            snap_id = snap.id
        else:
            snap = db.query(TeamReportSnapshot).order_by(desc(TeamReportSnapshot.id)).first()
            if not snap:
                print("No hay reportes en BD. Usa: full --to ... --generate")
                return 1
            payload = snap.payload or {}
            snap_id = snap.id
    finally:
        db.close()

    base = (getattr(Config, "BASE_URL", "") or "").rstrip("/")
    report_url = f"{base}/reportes/{snap_id}"
    html = render_weekly_report_html(payload, snap_id, report_url)
    text = _plain_text_summary(payload, report_url)
    mail_from = (Config.WEEKLY_REPORT_EMAIL_FROM or "").strip()
    if not mail_from:
        print("ERROR: WEEKLY_REPORT_EMAIL_FROM no está configurado en .env")
        return 1
    app_name = getattr(Config, "APP_NAME", "Sales Coach")
    m = payload.get("meta") or {}
    label = m.get("period_label_es", "Semana")

    send_weekly_report_email(
        html_body=html,
        text_body=text,
        subject=f"[PRUEBA {app_name}] Reporte semanal ({label})",
        mail_from=mail_from,
        recipients=[to_addr.strip()],
    )
    print("Reporte HTML enviado a:", to_addr)
    print("URL en dashboard:", report_url)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Probar correo del reporte semanal")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_dry = sub.add_parser("dry-run", help="Guarda HTML de vista previa; no envía correo")
    p_dry.add_argument("--from-db", action="store_true", help="Usar el último snapshot guardado")

    p_ping = sub.add_parser("ping", help="Envía un correo corto de prueba")
    p_ping.add_argument("--to", required=True, help="Correo destino (solo uno)")

    p_full = sub.add_parser("full", help="Envía el reporte HTML completo a un solo correo")
    p_full.add_argument("--to", required=True)
    p_full.add_argument(
        "--generate",
        action="store_true",
        help="Generar última semana cerrada en BD antes de enviar (como el job del viernes)",
    )

    args = p.parse_args()
    try:
        if args.cmd == "dry-run":
            return cmd_dry_run(args.from_db)
        if args.cmd == "ping":
            return cmd_ping(args.to)
        if args.cmd == "full":
            return cmd_full(args.to, args.generate)
    except Exception as e:
        print("Error:", e)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
