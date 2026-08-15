# -*- coding: utf-8 -*-
"""LLM 叙事层：基于原始数据事实，调用任意 OpenAI 兼容 API 生成「解读与判断」。

核心合规（与项目红线一致）：
- LLM 只能引用传入的数据事实（原始数字 + 来源），禁止编造任何数字/日期/来源/指标；
- 数据缺失时如实说明「数据暂缺」；
- 措辞用「可关注/可以留意」，禁绝对化指令；
- 直接看数字谈现象，不复述规则结论、不套用模板标签；
- 未配置 LLM_API_KEY 或调用失败 → 返回 {}，render 自动回退规则版 interp，流程不中断。

输出协议：采用「分隔符」而非 JSON——每板块以 `===板块名===` 独占一行开头，
后接 `@@分析` 子标记 + 多行叙事。多行 Markdown 用 JSON 字符串值极易因未转义换行/引号而非法，
分隔符协议对模型最自然、跨模型通用、解析鲁棒。

配置（环境变量，完全灵活）：
- LLM_API_KEY：API 密钥（必填）
- LLM_BASE_URL：API 基础 URL（必填）
- LLM_MODEL：模型名称（必填）

支持的 API 提供商示例：
- Groq: https://api.groq.com/openai/v1 + llama-3.3-70b-versatile
- Agnes: https://apihub.agnes-ai.com/v1 + agnes-2.0-flash
- OpenAI: https://api.openai.com/v1 + gpt-4o-mini
- 其他 OpenAI 兼容 API: 任意 base_url + 任意 model
"""
from __future__ import annotations

import logging
import os
import re

from .analyze import facts_text

log = logging.getLogger("ebc.llm")

# 五个板块的叙事键(与 render._section_* 对应),也是分隔符标记的合法名称
SECTIONS = ["overview", "equity", "etf", "bond", "convertible"]

SYSTEM_PROMPT = """你是中文金融资讯编辑，为每日市场早报（EBC Daily）撰写各板块的深度解读。

**你的读者**：初入市场的个人投资者，他们购买了 ETF 等资产但不具备专业金融知识。
**你的目标**：
1. 用通俗易懂的语言解释市场现象，帮助他们理解"发生了什么"和"为什么"
2. 提供教育性内容，帮助读者理解金融指标的含义和市场逻辑
3. 强调长期投资理念，不鼓励频繁交易

**数据红线（必须遵守）**：
1. 只能引用输入中的数据事实，严禁编造任何数字、日期、来源、指标名称；输入中没有的字段一律说「数据暂缺」
2. 严禁出现「建议买入/卖出/必涨/必跌/一定/必定」等绝对化指令。用「可以留意」「值得关注」「需要留意」等温和措辞

**写作风格**：
- 像一位耐心的朋友在解释市场，而不是冷冰冰的数据播报
- 解释现象背后的逻辑：例如"成交额放大到 X 亿，说明市场参与度提高，资金比较活跃"
- 用类比和通俗表达：例如"国债收益率上升，意味着债券价格下跌，因为债券价格与收益率是跷跷板关系"
- 适当加入教育性内容：帮助读者理解指标含义，例如"转股溢价率可以理解为可转债相对其对应股票的'加价'程度"
- 避免模板化标签（如「情绪偏热/偏冷/中性」），用具体数字和现象说话
- 对比多个维度：例如对比大盘股（上证50/沪深300）和小盘股（中证1000）的表现差异，解释风格轮动

**各板块分析要点**：

===overview===（全球市场）
- 美股三大指数的整体走势和分化
- 美债收益率变化的含义（10Y-2Y利差反映市场对经济预期）
- 大宗商品（原油、黄金、铜）的价格变化反映的通胀预期和经济景气度
- VIX恐慌指数的市场情绪指示作用
- 美元指数和人民币汇率对A股的影响

===equity===（A股市场）
- 核心指数对比：上证50（大盘价值）、沪深300（大盘）、中证500（中盘）、中证1000（小盘）、创业板（成长）、科创50（科技）、北证50（小微）
- 成交额变化的市场参与度含义
- 涨跌家数和涨跌停统计的市场广度
- 北向资金流向的外资态度
- 行业板块轮动反映的资金偏好
- 风格特征（大盘vs小盘、价值vs成长）的投资含义

===etf===（ETF焦点）
- 资金流向TOP3的赛道含义
- 溢价异常的风险提示
- 各类ETF的表现对比

===bond===（债券市场）
- 国债收益率变化的含义（收益率上升=债券价格下跌）
- 期限利差（10Y-1Y）反映的经济预期
- Shibor变化的资金面含义
- 债券ETF的表现

===convertible===（可转债）
- 转股溢价率分位的估值含义
- 破面数量增多的投资机会
- 强赎事件的风险提示

**输出格式**：依次输出五个板块，每个板块以一行动标记开头（标记独占一行）：
===overview===
===equity===
===etf===
===bond===
===convertible===

每板块以子标记 @@分析 独占一行开头，后接 2-4 个短段落（段落之间空一行）。每段 150-250 字，充分展开分析。

**禁止**：不要前言、不要解释、不要代码围栏、不要 JSON、不要「交易参考/参考思路」等内容。不要写板块大标题，不要用 Markdown 粗体标题。"""

# 匹配独占一行的 ===板块名=== 标记
_SECTION_RE = re.compile(r"^[ \t]*===[ \t]*(overview|equity|etf|bond|convertible)[ \t]*===[ \t]*$",
                         re.MULTILINE | re.IGNORECASE)
# 子标记 @@分析（@@参考 已废弃，若出现仅作分隔忽略其内容）
_SUB_RE = re.compile(r"^[ \t]*@@[ \t]*(分析|参考)[ \t]*$", re.MULTILINE | re.IGNORECASE)
# Qwen / 国产思考模型可能输出 <think>...</think> 推理块,需剥离
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    """剥离模型的思考/推理块（<think>...</think>、<thinking>...</thinking>）。

    某些模型默认开启 thinking 模式，
    推理块会消耗 max_tokens 额度且干扰分隔符解析，必须先剥离。
    """
    if not text:
        return text
    t = _THINK_RE.sub("", text)
    # 若模型输出未闭合的 <think>（max_tokens 截断导致），清除到文末
    t = _THINK_OPEN_RE.sub("", t)
    # 同时清理遗留的 <thinking> 标签
    t = re.sub(r"</?thinking[^>]*>", "", t, flags=re.IGNORECASE)
    return t.strip()


def _config() -> tuple[str, str, str]:
    """从环境变量读取 LLM 配置（完全灵活，无默认值）。"""
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    return api_key, base_url, model


def _user_prompt(facts: str, report_date) -> str:
    return f"""报告日期：{report_date}
以下是各板块的「数据事实」（均已标注来源，均为可查证真实数据，不含任何规则结论）：

{facts}

请基于以上数据事实，按系统提示的 ===板块名=== 分隔符格式，为五个板块（overview/equity/etf/bond/convertible）依次撰写「解读与判断」。
要求：只用上面出现的数字与事实，不可新增任何未出现的数值；缺失项如实写「数据暂缺」；直接看数字谈现象，不要复述规则结论、不要套用模板标签；每板块正文 120-200 字。直接从 ===overview=== 开始输出，不要前言。"""


def _call_llm(api_key: str, base_url: str, model: str, user_prompt: str) -> str | None:
    """调用任意 OpenAI 兼容 API（不引入 openai 依赖）。

    支持任何提供 /chat/completions 端点的 API 服务。
    """
    import requests  # noqa: WPS433
    
    if not base_url:
        log.error("LLM_BASE_URL 未配置")
        return None
    
    if not model:
        log.error("LLM_MODEL 未配置")
        return None
    
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 构建请求 payload（通用 OpenAI 格式）
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 3200,
    }
    
    # 某些 API 支持 thinking 模式控制，可选添加
    # 这里不强制添加，让 API 自行决定
    
    try:
        log.info("调用 LLM API: %s, 模型: %s", base_url, model)
        r = requests.post(url, headers=headers, json=payload, timeout=90)
        
        if r.status_code != 200:
            log.error("LLM HTTP %d [%s]：%s", r.status_code, model, r.text[:500])
            return None
        
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        
        if not content or not content.strip():
            log.warning("LLM 返回空内容 [%s]", model)
            return None
        
        return _strip_think(content)
    except Exception as e:  # noqa: BLE001
        log.error("LLM 调用失败 [%s]：%s", model, e)
        return None


def _parse_section(body: str) -> dict:
    """将单个板块正文解析为结构化叙事 {analysis:[段落]}。

    优先取 @@分析 子标记之后的内容；@@参考 已废弃，若出现则作为分隔，其内容忽略。
    若模型未用子标记，则整段视作分析。分析段落按空行切分。
    """
    if not body or not body.strip():
        return {}
    if _SUB_RE.search(body):
        parts = _SUB_RE.split(body)
        # split 带捕获组 → ['', '分析', content, '参考', content, ...]
        analysis_text = ""
        for i in range(1, len(parts) - 1, 2):
            marker = parts[i].strip()
            content = parts[i + 1]
            if marker.startswith("分析"):
                analysis_text = content
            # @@参考 内容丢弃
    else:
        # 容错：未用子标记，整段当分析
        analysis_text = body

    paras = [p.strip() for p in re.split(r"\n\s*\n", analysis_text.strip()) if p.strip()]
    if not paras and analysis_text.strip():
        # 段落间未空行时，按单换行兜底切分
        paras = [ln.strip() for ln in analysis_text.strip().split("\n") if ln.strip()]

    return {"analysis": paras}


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
        if parsed.get("analysis"):
            out[name] = parsed
    return out


def generate_narratives(data: dict, interp: dict, report_date) -> dict:
    """生成五板块 LLM 叙事。

    返回 {section: {analysis: [段落]}}；未配置 key 或调用/解析失败返回 {}，由 render 回退规则版。
    """
    api_key, base_url, model = _config()
    
    if not api_key:
        log.info("未配置 LLM_API_KEY，使用规则版叙事（降级）。")
        return {}
    
    if not base_url:
        log.warning("未配置 LLM_BASE_URL，使用规则版叙事（降级）。")
        return {}
    
    if not model:
        log.warning("未配置 LLM_MODEL，使用规则版叙事（降级）。")
        return {}
    
    facts = facts_text(data, interp)
    content = _call_llm(api_key, base_url, model, _user_prompt(facts, report_date))
    
    if not content:
        return {}
    
    out = _extract_sections(content)
    if not out:
        log.warning("LLM 返回无可用板块叙事，回退规则版。")
    else:
        log.info("LLM 叙事生成成功，板块：%s", "、".join(out.keys()))
    
    return out
