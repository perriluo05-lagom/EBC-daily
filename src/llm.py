# -*- coding: utf-8 -*-
"""LLM 叙事层:基于规则引擎给出的数据事实,调用 Groq(OpenAI 兼容)生成结构化解读。

核心合规(与项目红线一致):
- LLM 只能引用传入的数据事实,禁止编造任何数字/日期/来源/指标;
- 数据缺失时如实说明"数据暂缺";
- 措辞用"可关注/可以留意",禁绝对化指令;
- 未配置 LLM_API_KEY 或调用失败 → 返回 {},render 自动回退规则版 interp,流程不中断。

输出协议:采用「分隔符」而非 JSON——每板块以 `===板块名===` 独占一行开头,
后接多行 Markdown 叙事。多行 Markdown 用 JSON 字符串值极易因未转义换行/引号而非法,
分隔符协议对模型最自然、跨模型(lamma/qwen/kimi)通用、解析鲁棒。

配置(环境变量):
- LLM_API_KEY:Groq key(gsk_ 开头),在 console.groq.com/keys 创建。
- LLM_BASE_URL:默认 https://api.groq.com/openai/v1。
- LLM_MODEL:默认 llama-3.3-70b-versatile;中文求质量可切 qwen/qwen3-32b。
"""
from __future__ import annotations

import logging
import os
import re

from .config import LLM_BASE_URL_DEFAULT, LLM_MODEL_DEFAULT
from .analyze import facts_text

log = logging.getLogger("ebc.llm")

# 五个板块的叙事键(与 render._section_* 对应),也是分隔符标记的合法名称
SECTIONS = ["overview", "equity", "etf", "bond", "convertible"]

SYSTEM_PROMPT = """你是中文金融资讯编辑,为每日市场早报(EBC Daily)撰写各板块的「解读与判断」和「交易参考」。
严格遵守以下红线:
1. 只能引用输入中的数据事实,严禁编造任何数字、日期、来源、指标名称;输入中没有的字段一律说「数据暂缺」,绝不可臆造数值凑数。
2. 措辞必须克制,使用「可关注/可以留意/需要留意」,严禁出现「建议买入/卖出/必涨/必跌/一定/必定」等绝对化指令。
3. 输出格式:依次输出五个板块,每个板块以一行动标记开头(标记独占一行,前后无空格),直到下一个标记或结尾。标记与顺序固定为:
===overview===
===equity===
===etf===
===bond===
===convertible===
4. 每板块用两个子标记组织内容(子标记独占一行,前后无空格):
@@分析
(写 2-3 个短段落,每段一个完整意思;段落之间必须空一行;基于数据事实解读,可引用规则结论(如「规则结论指出:...」)但不得新增数字;不要写板块大标题,不要用 Markdown 粗体标题)
@@参考
数据事实：...(只复述输入事实,一行)
我的参考思路：...(基于事实的克制思路,一行)
今天可以扫一眼的：...(1-2条观察点,一行;概览板块可省略此条)
5. 「@@分析」「@@参考」「数据事实：」「我的参考思路：」「今天可以扫一眼的：」这些标记/前缀必须原样输出,不要加粗、不要加引号、不要加 Markdown 符号。
6. 只输出上述五个板块内容,不要前言、不要解释、不要代码围栏、不要 JSON。"""

# 匹配独占一行的 ===板块名=== 标记
_SECTION_RE = re.compile(r"^[ \t]*===[ \t]*(overview|equity|etf|bond|convertible)[ \t]*===[ \t]*$",
                         re.MULTILINE | re.IGNORECASE)
# 子标记 @@分析 / @@参考
_SUB_RE = re.compile(r"^[ \t]*@@[ \t]*(分析|参考)[ \t]*$", re.MULTILINE | re.IGNORECASE)
# 参考区三行前缀
_FACT_RE = re.compile(r"^[ \t]*数据事实[：:]\s*(.+)$", re.MULTILINE)
_IDEA_RE = re.compile(r"^[ \t]*我的参考思路[：:]\s*(.+)$", re.MULTILINE)
_WATCH_RE = re.compile(r"^[ \t]*今天可以扫一眼的[：:]\s*(.+)$", re.MULTILINE)


def _config() -> tuple[str, str, str]:
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", LLM_BASE_URL_DEFAULT).strip()
    model = os.environ.get("LLM_MODEL", LLM_MODEL_DEFAULT).strip()
    return api_key, base_url, model


def _user_prompt(facts: str, report_date) -> str:
    return f"""报告日期:{report_date}
以下是各板块的「数据事实 + 规则引擎结论」(均已标注来源,均为可查证真实数据):

{facts}

请基于以上事实,按系统提示的 ===板块名=== 分隔符格式,为五个板块(overview/equity/etf/bond/convertible)依次撰写解读。
规则:只用上面出现的数字与结论,不可新增任何未出现的数值;缺失项如实写「数据暂缺」;每板块解读正文 120-200 字。直接从 ===overview=== 开始输出,不要前言。"""


def _call_groq(api_key: str, base_url: str, model: str, user_prompt: str) -> str | None:
    """直接用 requests 调 OpenAI 兼容 chat/completions(不引入 openai 依赖)。"""
    import requests  # noqa: WPS433
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 2600,
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        log.warning("LLM 调用失败(%s): %s", model, e)
        return None


def _parse_section(body: str) -> dict:
    """将单个板块正文解析为结构化叙事 {analysis:[段落], facts, idea, watch}。

    优先按 @@分析 / @@参考 子标记切分;若模型未用子标记,则整段视作分析。
    分析段落按空行切分;参考三行按前缀(数据事实/我的参考思路/今天可以扫一眼的)提取。
    """
    if not body or not body.strip():
        return {}
    if _SUB_RE.search(body):
        parts = _SUB_RE.split(body)
        # split 带捕获组 → ['', '分析', content, '参考', content, ...]
        analysis_text, ref_text = "", ""
        for i in range(1, len(parts) - 1, 2):
            marker = parts[i].strip()
            content = parts[i + 1]
            if marker.startswith("分析"):
                analysis_text = content
            elif marker.startswith("参考"):
                ref_text = content
    else:
        # 容错:未用子标记,整段当分析
        analysis_text, ref_text = body, ""

    paras = [p.strip() for p in re.split(r"\n\s*\n", analysis_text.strip()) if p.strip()]
    if not paras and analysis_text.strip():
        # 段落间未空行时,按单换行兜底切分
        paras = [ln.strip() for ln in analysis_text.strip().split("\n") if ln.strip()]

    def _grab(regex: re.Pattern) -> str:
        m = regex.search(ref_text)
        return m.group(1).strip() if m else ""

    return {
        "analysis": paras,
        "facts": _grab(_FACT_RE),
        "idea": _grab(_IDEA_RE),
        "watch": _grab(_WATCH_RE),
    }


def _extract_sections(text: str) -> dict:
    """从分隔符格式的文本中提取各板块结构化叙事。

    每个 `===name===` 独占一行,其内容到下一个标记(或文末)为止,
    再经 _parse_section 解析为 {analysis, facts, idea, watch}。
    分析与参考均为空的板块不返回(由上层回退规则版)。
    """
    if not text:
        return {}
    # 去除可能的代码围栏,避免标记被包裹导致正则失配
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    marks = list(_SECTION_RE.finditer(t))
    if not marks:
        return {}
    out: dict[str, dict] = {}
    for i, m in enumerate(marks):
        name = m.group(1).lower()
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(t)
        parsed = _parse_section(t[start:end])
        if parsed.get("analysis") or parsed.get("facts") or parsed.get("idea") or parsed.get("watch"):
            out[name] = parsed
    return out


def generate_narratives(data: dict, interp: dict, report_date) -> dict:
    """生成五板块 LLM 叙事。

    返回 {section: narrative_md};未配置 key 或调用/解析失败返回 {},由 render 回退规则版。
    """
    api_key, base_url, model = _config()
    if not api_key:
        log.info("未配置 LLM_API_KEY,使用规则版叙事(降级)。")
        return {}
    facts = facts_text(data, interp)
    content = _call_groq(api_key, base_url, model, _user_prompt(facts, report_date))
    if not content:
        return {}
    out = _extract_sections(content)
    if not out:
        log.warning("LLM 返回无可用板块叙事,回退规则版。")
    else:
        log.info("LLM 叙事生成成功,板块:%s", ",".join(out.keys()))
    return out
