import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SERVICE_LABELS = {
    "blog_post":    "Blog Post",
    "product_desc": "Product Description",
    "social_pack":  "Social Media Pack",
    "newsletter":   "Email Newsletter",
}


def send_delivery_email(to_email: str, order: dict, content: str) -> None:
    smtp_host  = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port  = int(os.getenv("SMTP_PORT", "587"))
    smtp_user  = os.getenv("SMTP_USER")
    smtp_pass  = os.getenv("SMTP_PASS")
    from_email = os.getenv("FROM_EMAIL") or smtp_user
    biz_name   = os.getenv("BUSINESS_NAME", "AI Content Studio")

    if not smtp_user or not smtp_pass:
        raise RuntimeError("SMTP_USER and SMTP_PASS must be set in .env")

    service_name = SERVICE_LABELS.get(order.get("service_type", ""), "Content")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your {service_name} is Ready! ✅"
    msg["From"]    = f"{biz_name} <{from_email}>"
    msg["To"]      = to_email

    # Plain text fallback
    plain = (
        f"Hi there,\n\n"
        f"Your {service_name} is ready!\n\n"
        f"Topic: {order.get('topic', '')}\n"
        f"{'─' * 60}\n\n"
        f"{content}\n\n"
        f"{'─' * 60}\n"
        f"Thanks for using {biz_name}!\n"
    )

    # HTML version
    safe_content = (
        content
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
        .replace("**", "")
    )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:24px;color:#1f2937;">
  <div style="background:#2563eb;padding:20px 24px;border-radius:8px 8px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:22px;">{biz_name}</h1>
  </div>
  <div style="border:1px solid #e5e7eb;border-top:none;padding:28px;border-radius:0 0 8px 8px;">
    <h2 style="color:#2563eb;margin-top:0;">Your {service_name} is Ready!</h2>
    <p style="color:#6b7280;margin-bottom:20px;">
      <strong>Topic:</strong> {order.get('topic', '')}
    </p>
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">
    <div style="background:#f9fafb;padding:20px;border-radius:6px;line-height:1.7;white-space:pre-wrap;">
{safe_content}
    </div>
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
    <p style="color:#9ca3af;font-size:13px;margin:0;">
      Thanks for using {biz_name}! Reply to this email if you need revisions.
    </p>
  </div>
</body>
</html>"""

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, to_email, msg.as_string())
