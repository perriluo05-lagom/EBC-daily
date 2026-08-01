# -*- coding: utf-8 -*-
"""邮件发送层:QQ 邮箱 SMTP,失败重试 3 次。

配置从环境变量读取:MAIL_HOST/MAIL_PORT/MAIL_USER/MAIL_PASS/MAIL_FROM/MAIL_TO。
"""
from __future__ import annotations

import logging
import os
import smtplib
import time
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

log = logging.getLogger("ebc.emailer")

MAX_RETRIES = 3


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def send(subject: str, body: str) -> bool:
    host = _env("MAIL_HOST", "smtp.qq.com")
    port = int(_env("MAIL_PORT", "465") or "465")
    user = _env("MAIL_USER")
    pwd = _env("MAIL_PASS")
    sender = _env("MAIL_FROM", user)
    to_raw = _env("MAIL_TO")
    if not user or not pwd or not to_raw:
        log.error("邮件配置缺失(MAIL_USER/MAIL_PASS/MAIL_TO),跳过发送")
        return False
    recipients = [a.strip() for a in to_raw.split(",") if a.strip()]

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("EBC Daily", sender))
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if port == 465:
                srv = smtplib.SMTP_SSL(host, port, timeout=30)
            else:
                srv = smtplib.SMTP(host, port, timeout=30)
                srv.starttls()
            srv.login(user, pwd)
            srv.sendmail(sender, recipients, msg.as_string())
            srv.quit()
            log.info("邮件发送成功 -> %s", recipients)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("第 %d 次发送失败: %s", attempt, e)
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
    log.error("邮件发送最终失败")
    return False
