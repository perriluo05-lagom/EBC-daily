# -*- coding: utf-8 -*-
"""邮件 HTML 渲染测试:Markdown→HTML 转换、表格包裹、块级归一化。"""
import datetime as dt

from src import emailer, render
from tests.test_render import _data_all_missing, _interp_all_missing


def _sample_md() -> str:
    return render.render(
        _data_all_missing(), _interp_all_missing(),
        dt.date(2026, 8, 1), "2026-07-31",
    )


def test_md_to_html_is_full_document():
    html = emailer.md_to_html(_sample_md())
    assert html.startswith("<!DOCTYPE html>")
    assert "<html" in html
    assert "<style>" in html  # 样式块
    assert "viewport" in html  # 移动端适配


def test_table_converted_to_html_table():
    html = emailer.md_to_html(_sample_md())
    # Markdown 表格应转为真正的 <table>/<th>/<td>
    assert "<table>" in html
    assert "<th>" in html
    assert "<td>" in html
    # 表头文本应出现(概览表)
    assert "品种" in html


def test_table_wrapped_in_scroll_container():
    html = emailer.md_to_html(_sample_md())
    # 每个表格外层应有可横向滚动容器,适配手机窄屏
    assert html.count('<div class="ebc-tbl-wrap"><table>') == html.count("</table></div>")
    assert html.count('<div class="ebc-tbl-wrap">') >= 5  # 五大板块各一表


def test_normalize_inserts_blank_between_blocks():
    # 表格紧跟段落时,归一化应在二者间补空行,避免被解析进同一块
    md = "## 一、标题\n| a | b |\n| --- | --- |\n| 1 | 2 |\n**解读**:内容"
    normed = emailer._normalize_md(md)
    # 表格行(以 | 开头)与 **解读** 段落之间应有空行
    lines = normed.split("\n")
    # 找到最后一行表格(| 1 | 2 |)的下一条
    idx = lines.index("| 1 | 2 |")
    assert lines[idx + 1] == ""  # 空行
    assert lines[idx + 2] == "**解读**:内容"


def test_normalize_keeps_consecutive_table_rows_together():
    md = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
    normed = emailer.md_to_html(md)
    # 四行表格(表头+分隔+两数据行)应合并为单个 <table>
    assert normed.count("<table>") == 1
    assert normed.count("<tr>") == 3  # 表头 + 2 数据行


def test_no_raw_pipe_syntax_leaks():
    html = emailer.md_to_html(_sample_md())
    # 转换后不应残留 Markdown 表格分隔线原始文本
    assert "| --- |" not in html
    assert "| ---" not in html


def test_section_headers_present():
    html = emailer.md_to_html(_sample_md())
    for h in ["🌙 昨夜今晨概览", "📈 A股大盘温度", "💹 ETF焦点", "💼 债券市场", "🔄 可转债"]:
        assert h in html


def test_header_banner_with_date():
    """h1 应合并日期段落为渐变头部横幅（带 <span class="date">）。"""
    html = emailer.md_to_html(_sample_md())
    assert '<span class="date">' in html
    assert "2026年8月1日" in html
    assert "星期" in html
