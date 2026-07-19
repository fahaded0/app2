"""Email service using Resend.

All sends run inside `asyncio.to_thread` so they never block the FastAPI event loop.
"""
import os
import asyncio
import logging
from typing import Iterable, Optional

import resend
from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger("email_service")

_API_KEY = os.environ.get("RESEND_API_KEY", "")
_SENDER = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
_APP_URL = os.environ.get("APP_URL", "")

if _API_KEY:
    resend.api_key = _API_KEY


SEVERITY_COLOR = {
    "critical": "#DC2626",
    "danger":   "#DC2626",
    "warning":  "#D97706",
    "info":     "#0284C7",
}


def _build_html(
    title: str,
    severity: str,
    message: str,
    department: Optional[str] = None,
    item: Optional[str] = None,
    extra_rows: Optional[list[tuple[str, str]]] = None,
    cta_label: Optional[str] = "Open Alerts",
) -> str:
    color = SEVERITY_COLOR.get(severity, "#0284C7")
    rows: list[tuple[str, str]] = []
    if department:
        rows.append(("Department", department))
    if item:
        rows.append(("Item", item))
    rows.append(("Severity", severity.upper()))
    if extra_rows:
        rows.extend(extra_rows)
    rows_html = "".join(
        f"<tr><td style='padding:6px 12px;color:#475569;font-size:13px;'>{k}</td>"
        f"<td style='padding:6px 12px;font-weight:600;font-size:13px;color:#0F172A;'>{v}</td></tr>"
        for k, v in rows
    )
    cta_html = ""
    if _APP_URL and cta_label:
        cta_html = (
            f"<a href='{_APP_URL}/alerts' "
            "style='display:inline-block;padding:10px 22px;background:#0284C7;"
            "color:#ffffff;border-radius:6px;text-decoration:none;font-weight:700;"
            f"font-size:14px;'>{cta_label}</a>"
        )
    return f"""
<!doctype html>
<html><body style="margin:0;padding:0;background:#F1F5F9;font-family:-apple-system,Inter,Segoe UI,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F1F5F9;padding:32px 16px;">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;border:1px solid #E2E8F0;overflow:hidden;">
      <tr><td style="background:{color};color:#fff;padding:18px 24px;">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:2px;font-weight:700;opacity:.85;">Critical Medical Stock Monitor</div>
        <div style="font-size:20px;font-weight:800;margin-top:4px;">{title}</div>
      </td></tr>
      <tr><td style="padding:24px;">
        <p style="margin:0 0 16px 0;font-size:14px;color:#334155;line-height:1.5;">{message}</p>
        <table cellpadding="0" cellspacing="0" style="width:100%;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:6px;">
          {rows_html}
        </table>
        <div style="margin-top:22px;">{cta_html}</div>
        <p style="margin:22px 0 0 0;font-size:11px;color:#94A3B8;">
          This is an automated alert from the Critical Medical Stock Monitoring System.
          Do not reply to this email.
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>
"""


async def send_alert_email(
    to: Iterable[str],
    *,
    title: str,
    severity: str,
    message: str,
    department: Optional[str] = None,
    item: Optional[str] = None,
    extra_rows: Optional[list[tuple[str, str]]] = None,
) -> Optional[str]:
    """Send an alert email. Returns the Resend message id (or None on error).

    Recipients with empty/None values are skipped automatically.
    """
    if not _API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping email send")
        return None
    recipients = sorted({e.strip().lower() for e in to if e and "@" in e})
    if not recipients:
        return None
    html = _build_html(title, severity, message, department=department,
                       item=item, extra_rows=extra_rows)
    params = {
        "from": _SENDER,
        "to": recipients,
        "subject": f"[{severity.upper()}] {title}",
        "html": html,
    }
    try:
        result = await asyncio.to_thread(resend.Emails.send, params)
        msg_id = (result or {}).get("id")
        logger.info("Email sent id=%s to=%s", msg_id, recipients)
        return msg_id
    except Exception as e:
        logger.exception("Email send failed: %s", e)
        return None


async def send_report_email(
    to: Iterable[str],
    *,
    report_title: str,
    sender_name: str,
    message_body: str,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> Optional[str]:
    """Send a report as a PDF attachment via Resend.

    Resend expects attachments encoded as base64 strings.
    """
    if not _API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping report email")
        return None
    recipients = sorted({e.strip().lower() for e in to if e and "@" in e})
    if not recipients:
        return None
    import base64
    encoded = base64.b64encode(pdf_bytes).decode("ascii")
    html = f"""
<!doctype html>
<html><body style="margin:0;padding:0;background:#F1F5F9;font-family:-apple-system,Inter,Segoe UI,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F1F5F9;padding:32px 16px;">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;border:1px solid #E2E8F0;overflow:hidden;">
      <tr><td style="background:#0284C7;color:#fff;padding:18px 24px;">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:2px;font-weight:700;opacity:.85;">Critical Medical Stock Monitor</div>
        <div style="font-size:20px;font-weight:800;margin-top:4px;">{report_title}</div>
      </td></tr>
      <tr><td style="padding:24px;">
        <p style="margin:0 0 12px 0;font-size:14px;color:#334155;line-height:1.6;">
          {message_body.replace(chr(10), '<br/>')}
        </p>
        <p style="margin:0;font-size:13px;color:#475569;">
          The full report is attached as <strong>{pdf_filename}</strong>.
        </p>
        <p style="margin:22px 0 0 0;font-size:11px;color:#94A3B8;">
          Sent by {sender_name} via the Critical Medical Stock Monitoring System.
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>
"""
    params = {
        "from": _SENDER,
        "to": recipients,
        "subject": f"Report — {report_title}",
        "html": html,
        "attachments": [{
            "filename": pdf_filename,
            "content": encoded,
            "content_type": "application/pdf",
        }],
    }
    try:
        result = await asyncio.to_thread(resend.Emails.send, params)
        msg_id = (result or {}).get("id")
        logger.info("Report email sent id=%s to=%s file=%s", msg_id, recipients, pdf_filename)
        return msg_id
    except Exception as e:
        logger.exception("Report email send failed: %s", e)
        return None


# ---------- Escalation recipients ----------
"""
Stored as a single document keyed by role: {"_id": "...", "role": "supply_officer", "email": "x@y.com"}
"""

async def get_escalation_recipients(db: AsyncDatabase) -> list[dict]:
    """Return all role->email entries."""
    return await db.escalation_recipients.find({}, {"_id": 0}).to_list(100)


async def set_escalation_recipient(db: AsyncDatabase, role: str, email: Optional[str]) -> None:
    if not email:
        await db.escalation_recipients.delete_one({"role": role})
        return
    await db.escalation_recipients.update_one(
        {"role": role},
        {"$set": {"role": role, "email": email.strip().lower()}},
        upsert=True,
    )


async def resolve_recipients_for_roles(db: AsyncDatabase, roles: Iterable[str]) -> list[str]:
    """Find emails of recipients for the given roles.

    Combines:
      1. All users with `is_active=True` whose `role` is in `roles` and who have an email.
      2. Any rows in `escalation_recipients` matching the role (for roles that have no user).
    """
    roles = list(roles)
    if not roles:
        return []
    emails: set[str] = set()
    async for u in db.users.find(
        {"role": {"$in": roles}, "is_active": True, "email": {"$ne": None}},
        {"_id": 0, "email": 1},
    ):
        if u.get("email"):
            emails.add(u["email"].strip().lower())
    async for r in db.escalation_recipients.find(
        {"role": {"$in": roles}}, {"_id": 0, "email": 1}
    ):
        if r.get("email"):
            emails.add(r["email"].strip().lower())
    return sorted(emails)
