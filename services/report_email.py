"""
Weekly team report: render HTML email and send via SMTP (viernes, job del bot).
Configure SMTP_* y credenciales en el entorno; sin SMTP el envío se omite sin fallar el job.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import List, Optional

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import Config

log = logging.getLogger(__name__)

# Default recipients list is empty — configure via WEEKLY_REPORT_EMAIL_RECIPIENTS
# (comma-separated) in the environment. If empty, weekly emails are skipped.
WEEKLY_REPORT_RECIPIENTS_DEFAULT: List[str] = []


def _template_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "dashboard_app", "templates")


def weekly_report_recipients() -> List[str]:
    raw = (Config.WEEKLY_REPORT_EMAIL_RECIPIENTS or os.getenv("WEEKLY_REPORT_EMAIL_RECIPIENTS") or "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return list(WEEKLY_REPORT_RECIPIENTS_DEFAULT)


def render_weekly_report_html(payload: dict, snap_id: int, report_url: str) -> str:
    p = dict(payload or {})

    # Pre-sort categories by accuracy ascending so the template doesn't need to (avoids
    # Jinja2 sort failures when accuracy_pct is None for some rows).
    kv = p.get("knowledge_vertical") or {}
    by_cat = kv.get("by_category") or []
    try:
        by_cat_sorted = sorted(by_cat, key=lambda r: (r.get("accuracy_pct") or 0))
    except Exception:
        by_cat_sorted = by_cat
    p["knowledge_vertical"] = {**kv, "by_category": by_cat_sorted}

    env = Environment(
        loader=FileSystemLoader(_template_dir()),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("email_report_weekly.html")
    return tmpl.render(payload=p, snap_id=snap_id, report_url=report_url or "")


def _plain_text_summary(payload: dict, report_url: str) -> str:
    m = (payload or {}).get("meta") or {}
    label = m.get("period_label_es", "Reporte semanal")
    team = ((payload or {}).get("team") or {}).get("metrics") or {}
    lines = [
        f"{Config.APP_NAME} — Reporte semanal del equipo",
        label,
        "",
        f"Enviadas: {team.get('sent', 0)} · Respondidas: {team.get('answered', 0)} · Correctas: {team.get('correct', 0)}",
        "",
        f"Ver versión HTML en el navegador: {report_url}",
        "",
        "(Si no ves bien el mensaje, abre el enlace.)",
    ]
    return "\n".join(lines)


def _send_via_resend(
    *,
    html_body: str,
    text_body: str,
    subject: str,
    mail_from: str,
    recipients: List[str],
) -> None:
    """Envía vía https://resend.com (puerto 443, evita bloqueos SMTP del host)."""
    api_key = (getattr(Config, "RESEND_API_KEY", "") or os.getenv("RESEND_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY no configurado")

    timeout = int(getattr(Config, "SMTP_TIMEOUT", 25) or 25)
    from_addr = mail_from
    if "<" not in from_addr:
        from_addr = formataddr((f"{Config.APP_NAME} — Reporte", mail_from))

    payload = {
        "from": from_addr,
        "to": recipients,
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Resend: error de red ({e})") from e

    if resp.status_code >= 300:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise RuntimeError(f"Resend {resp.status_code}: {detail}")
    log.info("Weekly report email sent via Resend to %d recipient(s)", len(recipients))


def send_weekly_report_email(
    *,
    html_body: str,
    text_body: str,
    subject: str,
    mail_from: str,
    recipients: List[str],
) -> None:
    # Preferimos Resend si está configurado (HTTP 443; evita bloqueos SMTP típicos de Railway)
    if (getattr(Config, "RESEND_API_KEY", "") or os.getenv("RESEND_API_KEY") or "").strip():
        return _send_via_resend(
            html_body=html_body,
            text_body=text_body,
            subject=subject,
            mail_from=mail_from,
            recipients=recipients,
        )

    host = (Config.SMTP_HOST or "").strip()
    if not host:
        raise RuntimeError("SMTP_HOST no configurado y RESEND_API_KEY ausente")

    port = int(Config.SMTP_PORT or 587)
    user = (Config.SMTP_USER or "").strip()
    password = (Config.SMTP_PASSWORD or "").strip()
    use_tls = Config.SMTP_USE_TLS
    use_ssl = Config.SMTP_USE_SSL

    if not user or not password:
        raise RuntimeError("SMTP_USER / SMTP_PASSWORD no configurados")

    timeout = int(getattr(Config, "SMTP_TIMEOUT", 25) or 25)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((f"{Config.APP_NAME} — Reporte", mail_from))
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    # Algunos hosts (Railway, otros PaaS) no tienen ruta IPv6 saliente y fallan con
    # "Errno 101 Network is unreachable" al intentar la A/AAAA del SMTP server.
    # Forzamos IPv4 salvo que SMTP_FORCE_IPV4=false.
    force_ipv4 = str(os.getenv("SMTP_FORCE_IPV4", "true")).strip().lower() != "false"
    resolved_host = host
    if force_ipv4:
        try:
            infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            if infos:
                resolved_host = infos[0][4][0]
                log.info("SMTP forzando IPv4: %s -> %s", host, resolved_host)
        except Exception as e:
            log.warning("No se pudo resolver IPv4 para %s (%s); usando hostname", host, e)

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(resolved_host, port, context=context, timeout=timeout) as server:
                if resolved_host != host:
                    server.ehlo(host)
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(resolved_host, port, timeout=timeout) as server:
                server.ehlo(host)
                if use_tls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                    server.ehlo(host)
                server.login(user, password)
                server.send_message(msg)
    except (TimeoutError, socket.timeout) as e:
        raise RuntimeError(
            f"SMTP: tiempo de espera agotado ({timeout}s) conectando a {host}:{port}. "
            "Comprueba firewall, que el servicio permita salida al puerto, o prueba SMTP_TIMEOUT más alto."
        ) from e
    except OSError as e:
        errno = getattr(e, "errno", None)
        msg_l = str(e).lower()
        if errno == 101 or "network is unreachable" in msg_l:
            raise RuntimeError(
                f"SMTP: red no alcanzable a {host}:{port}. En algunos hosts solo hay IPv4: "
                "deja SMTP_FORCE_IPV4=true (default) o usa un relay (SendGrid/Resend/SES)."
            ) from e
        if "timed out" in msg_l or errno in (110, 10060):
            raise RuntimeError(
                f"SMTP: sin respuesta de {host}:{port} en {timeout}s. "
                "Algunos proveedores bloquean SMTP saliente; prueba otro puerto o un relay."
            ) from e
        raise

    log.info("Weekly report email sent to %d recipient(s)", len(recipients))


def try_send_weekly_report_email(payload: dict, snap_id: int, report_url: str) -> Optional[str]:
    """
    Send HTML report if SMTP is configured. Returns None on success, error string on failure.
    If SMTP is missing, returns a skip reason (no exception).
    """
    if not Config.WEEKLY_REPORT_EMAIL_ENABLED:
        log.info("Weekly report email disabled (WEEKLY_REPORT_EMAIL_ENABLED=false)")
        return None

    host = (Config.SMTP_HOST or "").strip()
    if not host:
        log.warning("Weekly report email skipped: set SMTP_HOST, SMTP_USER, SMTP_PASSWORD")
        return None

    mail_from = (Config.WEEKLY_REPORT_EMAIL_FROM or "").strip()
    if not mail_from:
        return "WEEKLY_REPORT_EMAIL_FROM no configurado — no puedo enviar sin remitente"
    recipients = weekly_report_recipients()
    if not recipients:
        log.warning("Weekly report email skipped: no recipients")
        return None

    m = (payload or {}).get("meta") or {}
    label = m.get("period_label_es", "Semana")
    subject = f"{Config.APP_NAME} — Reporte semanal equipo ({label})"

    try:
        html = render_weekly_report_html(payload, snap_id, report_url)
        text = _plain_text_summary(payload, report_url)
        send_weekly_report_email(
            html_body=html,
            text_body=text,
            subject=subject,
            mail_from=mail_from,
            recipients=recipients,
        )
        return None
    except Exception as e:
        log.exception("Weekly report email failed: %s", e)
        return str(e)
