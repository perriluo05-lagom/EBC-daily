# -*- coding: utf-8 -*-
"""邮件发送层:QQ 邮箱 SMTP,失败重试 3 次。

正文以 HTML 发送:Markdown 先转为 HTML,再套用莫兰迪浅色邮件样式,
保证 PC / 手机端表格均为真正的表格、层次清晰。配置从环境变量读取:
MAIL_HOST/MAIL_PORT/MAIL_USER/MAIL_PASS/MAIL_FROM/MAIL_TO。
"""
from __future__ import annotations

import logging
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

log = logging.getLogger("ebc.emailer")

MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# 莫兰迪浅色邮件样式:雾蓝 #728ec7 点缀,白底卡片,9px 圆角,仅横向细线,
# 交替行底色,表格外层可横向滚动以适配手机窄屏。
# ---------------------------------------------------------------------------
_CSS = """
*{box-sizing:border-box;}
body{margin:0;padding:24px 6px;background:#f3f5f8;
  font-family:"Microsoft YaHei","PingFang SC","Helvetica Neue",Arial,sans-serif;
  color:#2b2b2b;font-size:15px;line-height:1.75;-webkit-text-size-adjust:100%;}
.ebc-wrap{max-width:600px;margin:0 auto;background:#ffffff;border-radius:9px;
  overflow:hidden;box-shadow:0 3px 10px rgba(43,43,43,0.06);}
.ebc-content{padding:28px 24px 24px;}
h1{margin:0 0 14px;padding-bottom:14px;font-size:21px;font-weight:700;
  color:#2b2b2b;letter-spacing:.5px;border-bottom:2px solid #728ec7;}
h2{margin:26px -24px 14px;padding:11px 24px;font-size:16px;font-weight:600;
  color:#ffffff;background:#728ec7;letter-spacing:.3px;}
blockquote{margin:0 0 16px;padding:11px 14px;background:#eef2f8;
  border-left:3px solid #728ec7;border-radius:6px;color:#5a5d63;font-size:13.5px;}
.ebc-tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;
  margin:0 0 16px;border-radius:6px;}
table{width:100%;border-collapse:collapse;font-size:13.5px;min-width:380px;background:#fff;}
th{padding:9px 11px;text-align:left;font-weight:600;color:#ffffff;
  background:#728ec7;white-space:nowrap;}
td{padding:8px 11px;border-bottom:1px solid #eef0f3;color:#2b2b2b;white-space:nowrap;}
tr:nth-child(even) td{background:#f7f9fb;}
tr:last-child td{border-bottom:none;}
strong{color:#3a5a8c;font-weight:600;}
ul{margin:6px 0 16px;padding-left:20px;}
li{margin:4px 0;}
hr{margin:22px 0;border:none;border-top:1px solid #e4e7ec;}
p{margin:0 0 14px;}
@media only screen and (max-width:480px){
  body{padding:12px 0;}
  .ebc-content{padding:20px 16px;}
  h2{margin:22px -16px 12px;padding:10px 16px;font-size:15px;}
  h1{font-size:19px;}
  table{font-size:13px;min-width:340px;}
  th,td{padding:7px 8px;}
}
"""


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _block_type(ln: str) -> str:
    s = ln.strip()
    if not s:
        return "blank"
    if s.startswith("#"):
        return "header"
    if s.startswith("|"):
        return "table"
    if s.startswith(">"):
        return "quote"
    if s.startswith(("- ", "* ", "+ ")):
        return "list"
    if s in ("---", "***", "___"):
        return "hr"
    return "para"


def _normalize_md(md: str) -> str:
    """在块级元素之间补空行,提升 Markdown→HTML 解析稳定性(表头/表格/段落相邻不分块)。"""
    out: list[str] = []
    prev: str | None = None
    for ln in md.split("\n"):
        cur = _block_type(ln)
        if cur == "blank":
            if out and out[-1] != "":
                out.append("")
            prev = None
            continue
        if prev is not None and cur != prev and out and out[-1] != "":
            out.append("")
        out.append(ln)
        prev = cur
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def md_to_html(md: str) -> str:
    """Markdown 正文 → HTML 邮件(表格/列表/引用块,莫兰迪浅色样式)。

    未安装 markdown 库时回退为纯文本(包在 <pre> 里),保证流程不中断。
    """
    normed = _normalize_md(md)
    try:
        import markdown  # type: ignore
    except ImportError:
        log.warning("未安装 markdown 库,HTML 邮件回退纯文本")
        return (
            '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "</head><body><pre>%s</pre></body></html>" % normed.replace("<", "&lt;")
        )
    body = markdown.markdown(
        normed,
        extensions=["tables", "sane_lists", "nl2br"],
        output_format="html5",
    )
    # 表格外包一层可横向滚动容器,适配手机窄屏
    body = body.replace("<table>", '<div class="ebc-tbl-wrap"><table>')
    body = body.replace("</table>", "</table></div>")
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>{_CSS}</style></head><body>"
        f'<div class="ebc-wrap"><div class="ebc-content">{body}</div></div>'
        "</body></html>"
    )


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

    # multipart/alternative:同时附纯文本兜底 + HTML 正文
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(md_to_html(body), "html", "utf-8"))
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
    log.error("邮件最终发送失败")
    return False
