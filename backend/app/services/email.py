import smtplib
from email.message import EmailMessage

from backend.app.core.config import get_settings


def send_email(to_email: str, subject: str, body: str, html_body: str | None = None) -> bool:
    settings = get_settings()
    if not settings.smtp_host:
        return False
    # Ospiti, profili dei minori e account eliminati hanno un indirizzo finto
    # (.invalid): a quelli non si scrive.
    if to_email.lower().endswith(".invalid"):
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
    return True


def event_announcement_html(event_name: str, title: str, body: str) -> str:
    escaped_body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    escaped_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    escaped_event = event_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#0d0d0f;color:#f5efe0;font-family:Arial,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0d0d0f;padding:24px;">
      <tr>
        <td>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;margin:auto;background:#1e1d1a;border:1px solid #3a352d;border-radius:8px;">
            <tr>
              <td style="padding:24px;">
                <p style="margin:0 0 8px;color:#9a9aa5;font-size:12px;font-weight:bold;letter-spacing:.08em;text-transform:uppercase;">Mull2Five</p>
                <h1 style="margin:0 0 8px;font-size:24px;line-height:1.2;">{escaped_title}</h1>
                <p style="margin:0 0 20px;color:#9a9aa5;">{escaped_event}</p>
                <div style="font-size:16px;line-height:1.55;white-space:pre-wrap;">{escaped_body}</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
