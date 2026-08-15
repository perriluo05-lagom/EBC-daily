# -*- coding: utf-8 -*-
"""邮件发送层：QQ 邮箱 SMTP，失败重试 3 次。

正文以 HTML 发送：Markdown 先转为 HTML，再套用深海军蓝主色邮件样式，
保证 PC / 手机端表格均为真正的表格、层次清晰。配置从环境变量读取：
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
# 邮件样式：深靛蓝渐变头部横幅 + emoji 板块标题 + 彩色下划线，
# 白底圆角卡片、简约表格（无交替底色，表头深靛蓝），
# 适配手机窄屏横向滚动。整体简约现代，参考 Newsletter 风格。
# ---------------------------------------------------------------------------
_CSS = """
*{box-sizing:border-box;}
body{margin:0;padding:24px 6px;background:#f5f7fa;
  font-family:"Microsoft YaHei","PingFang SC","Helvetica Neue",Arial,sans-serif;
  color:#2c3e50;font-size:15px;line-height:1.85;-webkit-text-size-adjust:100%;}
.ebc-wrap{max-width:640px;margin:0 auto;background:#ffffff;border-radius:16px;
  overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,0.08);}
.ebc-content{padding:0 32px 32px;}
h1{margin:0 -32px 32px;padding:40px 32px;font-size:26px;font-weight:700;
  color:#ffffff;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
  letter-spacing:1px;line-height:1.5;text-align:center;}
h1 .date{display:block;font-size:15px;font-weight:400;opacity:.9;
  margin-top:8px;letter-spacing:.5px;}
h2{margin:36px 0 18px;padding:0 0 12px;font-size:18px;font-weight:600;
  color:#667eea;border-bottom:3px solid #667eea;background:none;letter-spacing:.5px;}
blockquote{margin:0 0 18px;padding:14px 18px;background:#f8f9fc;
  border-left:4px solid #667eea;border-radius:4px;font-size:14px;color:#5a6066;
  line-height:1.8;}
.ebc-tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;
  margin:0 0 24px;border-radius:10px;border:1px solid #e8ecf3;
  box-shadow:0 2px 8px rgba(0,0,0,0.04);}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:380px;background:#fff;}
th{padding:12px 14px;text-align:left;font-weight:600;color:#ffffff;
  background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
  white-space:nowrap;letter-spacing:.5px;}
td{padding:11px 14px;border-bottom:1px solid #f0f2f5;color:#2c3e50;white-space:nowrap;}
tr:nth-child(even){background:#fafbfc;}
tr:last-child td{border-bottom:none;}
tr:hover{background:#f5f7fa;}
strong{color:#667eea;font-weight:600;}
ul{margin:8px 0 18px;padding-left:22px;}
li{margin:6px 0;line-height:1.8;}
hr{margin:32px 0;border:none;border-top:2px solid #e8ecf3;}
p{margin:0 0 16px;}
@media only screen and (max-width:480px){
  body{padding:12px 0;}
  .ebc-content{padding:0 20px 20px;}
  h1{margin:0 -20px 24px;padding:28px 20px;font-size:22px;}
  h2{margin:28px 0 14px;font-size:16px;}
  table{font-size:13px;min-width:340px;}
  th,td{padding:9px 10px;}
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


def _post_process_header(body: str) -> str:
    """将 h1 与紧随其后的日期段落合并为渐变头部横幅（日期副标题）。"""
    import re as _re
    # 匹配 <h1>...</h1> 后紧跟的 <p>日期</p>，合并为带副标题的 h1
    pat = _re.compile(r"<h1>(.*?)</h1>\s*<p>(\d{4}年[^<]*?星期[一二三四五六日])</p>",
                      _re.DOTALL)
    m = pat.search(body)
    if not m:
        return body
    title = m.group(1).strip()
    date = m.group(2).strip()
    new_h1 = f'<h1>{title}<br><span class="date">{date}</span></h1>'
    return body[:m.start()] + new_h1 + body[m.end():]


def md_to_html(md: str) -> str:
    """Markdown 正文 → HTML 邮件(渐变头部横幅 + 表格/列表/引用块)。

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
    # 合并 h1 与日期段落为渐变头部横幅
    body = _post_process_header(body)
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
