# -*- coding: utf-8 -*-
"""东方财富搜索页「领涨概念」提取（搜索页 = https://so.eastmoney.com/web/s?keyword=XXX）。

页面上的 ``<div class="topconcept">`` 由前端 JS 从 push2 的 jsonp 接口取数后渲染：
    https://push2.eastmoney.com/api/qt/clist/get?...&fs=m:90+t:3&fid=f3&pz=10
⇒ 与 ``em_lead_concept.py`` **同源同口径**（那里走 API，这里走页面 DOM）。

两条腿
------
1) 实时：Playwright 渲染搜索页（先把 ``em_cookie`` 的真实 cookie 注入浏览器上下文），
   等 ``div.topconcept`` 出现后取 DOM 解析。push2 被风控/封禁时该块**恒为空**（实测）。
2) 离线：``--html 文件`` 直接解析已保存的页面/片段 —— 页面能打开但接口被限流时，
   人工另存一份 HTML 即可继续入库。

输出：控制台 markdown 表 + 可选 ``--json`` / ``--csv``。

用法
----
    python em_so_topconcept.py                        # 实时抓（默认关键词：华茂股份）
    python em_so_topconcept.py --keyword 泰慕士 --csv topconcept.csv
    python em_so_topconcept.py --html so_saved.html --json topconcept.json
    python em_so_topconcept.py --no-refresh-cookie    # 只用已保存 cookie，不联网刷新
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import em_cookie                                   # noqa: E402

DEFAULT_KEYWORD = "华茂股份"
SEARCH_URL = "https://so.eastmoney.com/web/s?keyword={kw}"
WAIT_MS = 1500
SCROLL_ROUNDS = 6
COLS = ["rank", "board_name", "chg_pct", "lead_name"]


# ------------------------------------------------------------------ 解析

class _TopconceptParser(HTMLParser):
    """抽 ``div.topconcept`` 里的 ``table.topconcept_table`` 三列：名称/涨跌幅/领涨股。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._depth = 0                # >0 表示在 div.topconcept 内
        self._cells: list[str] = []    # 当前 tr 已闭合的 td 文本
        self._anchors: list[str] = []  # 当前 tr 内 <a> 的可见文本
        self._buf: list[str] = []      # 当前 td 的全部可见文本
        self._abuf: list[str] = []     # 当前 <a> 的可见文本
        self._in_td = False
        self._in_a = False

    # -- helpers
    @staticmethod
    def _cls(attrs) -> list[str]:
        for k, v in attrs:
            if k == "class" and v:
                return v.split()
        return []

    @staticmethod
    def _text(buf) -> str:
        return re.sub(r"\s+", " ", "".join(buf)).strip()

    # -- HTMLParser hooks
    def handle_starttag(self, tag, attrs):
        cls = self._cls(attrs)
        if tag == "div":
            if not self._depth and "topconcept" in cls and not (
                    {"topconcept_t", "topconcept_list"} & set(cls)):
                self._depth = 1
                return
            if self._depth:
                self._depth += 1
        if not self._depth:
            return
        if tag == "tr":
            self._cells, self._anchors = [], []
        elif tag == "td":
            self._in_td, self._buf = True, []
        elif tag == "a":
            self._in_a, self._abuf = True, []

    def handle_data(self, data):
        if not self._depth:
            return
        if self._in_td:
            self._buf.append(data)
        if self._in_a:
            self._abuf.append(data)

    def handle_endtag(self, tag):
        if not self._depth:
            return
        if tag == "a" and self._in_a:
            t = self._text(self._abuf)
            if t:
                self._anchors.append(t)
            self._in_a, self._abuf = False, []
        elif tag == "td" and self._in_td:
            self._in_td = False
            self._cells.append(self._text(self._buf))
        elif tag == "tr":
            if len(self._cells) >= 3:
                name = self._anchors[0] if self._anchors else re.sub(r"^\d+", "", self._cells[0])
                lead = self._anchors[-1] if self._anchors else self._cells[2]
                rank_m = re.match(r"^\s*(\d+)", self._cells[0])
                self.rows.append({
                    "rank": int(rank_m.group(1)) if rank_m else len(self.rows) + 1,
                    "board_name": name.strip(),
                    "chg_pct": self._cells[1],
                    "lead_name": lead.strip(),
                })
            self._cells, self._anchors, self._buf, self._abuf = [], [], [], []
        elif tag == "div":
            self._depth -= 1


def parse_html(html: str) -> list[dict]:
    p = _TopconceptParser()
    p.feed(html)
    p.close()
    return p.rows


# ------------------------------------------------------------------ 实时抓取

def fetch_rendered(keyword: str = DEFAULT_KEYWORD, refresh_cookie: bool = True,
                   verbose: bool = True) -> tuple[str | None, list[dict]]:
    """渲染搜索页并取回 topconcept 容器的 outerHTML + 解析结果。拿不到返回 (None, [])。"""
    from playwright.sync_api import sync_playwright

    jar = em_cookie.ensure(force=refresh_cookie, verbose=verbose) if refresh_cookie \
        else em_cookie.load()
    url = SEARCH_URL.format(kw=quote(keyword))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(user_agent=em_cookie.UA)
        n = em_cookie.apply(ctx, jar)
        if verbose:
            print(f"  已注入 {n} 个 cookie 到浏览器上下文")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        loc = page.locator("div.topconcept")
        for _ in range(SCROLL_ROUNDS):
            if loc.count():
                break
            page.wait_for_timeout(WAIT_MS)
            page.mouse.wheel(0, 1200)
        html = loc.first.evaluate("el => el.outerHTML") if loc.count() else None
        browser.close()

    return html, (parse_html(html) if html else [])


# ------------------------------------------------------------------ 输出

def render_markdown(rows: list[dict]) -> str:
    out = ["领涨概念", "", "| 序号 | 名称 | 涨跌幅 | 领涨股 |", "|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['rank']} | {r['board_name']} | {r['chg_pct']} | {r['lead_name']} |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="东方财富搜索页「领涨概念」提取")
    ap.add_argument("-k", "--keyword", default=DEFAULT_KEYWORD, help=f"搜索关键词（默认 {DEFAULT_KEYWORD}）")
    ap.add_argument("--html", dest="html_path", help="离线模式：解析已保存的 HTML 文件（不联网）")
    ap.add_argument("--json", dest="json_path", help="写入 JSON")
    ap.add_argument("--csv", dest="csv_path", help="写入 CSV")
    ap.add_argument("--no-refresh-cookie", action="store_true",
                    help="不刷新 cookie，只用 em_cookie.json 里已有的")
    args = ap.parse_args()

    if args.html_path:
        with open(args.html_path, encoding="utf-8", errors="replace") as fh:
            html = fh.read()
        rows = parse_html(html)
        src = args.html_path
    else:
        html, rows = fetch_rendered(args.keyword, refresh_cookie=not args.no_refresh_cookie)
        src = SEARCH_URL.format(kw=quote(args.keyword))
        if html is None:
            print(f"未渲染出 div.topconcept（数据源 push2 不可达）—— 页面：{src}", file=sys.stderr)
            return 1

    if not rows:
        print(f"未解析到任何行：{src}", file=sys.stderr)
        return 1

    print(render_markdown(rows))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump({"source": src, "count": len(rows), "rows": rows},
                      fh, ensure_ascii=False, indent=2)
        print(f"\n[JSON] {args.json_path}（{len(rows)} 行）", file=sys.stderr)
    if args.csv_path:
        with open(args.csv_path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            w.writeheader()
            w.writerows(rows)
        print(f"[CSV] {args.csv_path}（{len(rows)} 行）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
