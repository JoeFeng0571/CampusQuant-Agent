from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def get_email_config() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "465").strip() or "465"),
        "username": os.getenv("SMTP_USERNAME", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_email": os.getenv("SMTP_FROM_EMAIL", "").strip() or os.getenv("SMTP_USERNAME", "").strip(),
        "from_name": os.getenv("SMTP_FROM_NAME", "CampusQuant").strip() or "CampusQuant",
        "use_ssl": os.getenv("SMTP_USE_SSL", "true").strip().lower() not in {"0", "false", "no"},
    }


def is_email_configured() -> bool:
    cfg = get_email_config()
    return bool(cfg["host"] and cfg["port"] and cfg["username"] and cfg["password"] and cfg["from_email"])


def send_verification_email(to_email: str, code: str, purpose: str) -> None:
    cfg = get_email_config()
    if not is_email_configured():
        raise RuntimeError("SMTP not configured")

    action_text = "登录" if purpose == "login" else "注册"
    msg = EmailMessage()
    msg["Subject"] = f"CampusQuant {action_text}验证码"
    msg["From"] = f"{cfg['from_name']} <{cfg['from_email']}>"
    msg["To"] = to_email
    msg.set_content(
        f"您好，\n\n"
        f"您本次用于{action_text}的验证码是：{code}\n"
        f"验证码 10 分钟内有效，请勿泄露给他人。\n\n"
        f"如果这不是您的操作，请忽略本邮件。\n"
    )

    if cfg["use_ssl"]:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15) as server:
            server.login(cfg["username"], cfg["password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            server.starttls()
            server.login(cfg["username"], cfg["password"])
            server.send_message(msg)
