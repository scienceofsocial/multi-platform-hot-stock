# -*- coding: utf-8 -*-
"""东方财富「领涨概念」抓取（概念板块按涨跌幅降序前 N）。

数据源与东方财富搜索页（https://so.eastmoney.com/web/s?keyword=XXX）该模块同源：
    <host>/api/qt/clist/get    （host 见 URLS，默认 push2，被路径级风控时回退 push2test）
    fs=m:90+t:3  → 概念板块；fid=f3 + po=1 → 按涨跌幅降序

字段映射
    f12 板块代码(BKxxxx)   f14 板块名称   f3 涨跌幅%   f4 涨跌额
    f128 领涨股名称        f140 领涨股代码  f141 领涨股市场(0=深/1=沪)
    f136 领涨股涨跌幅%     f62 主力净流入(元)

★ 通道要点（踩坑记录，勿改回 requests/curl）
    push2 按 **TLS/HTTP 指纹** 做风控：`requests` / `httpx` / 系统 `curl.exe`(Schannel) /
    裸 socket 一律被 RST（curl 56 "Connection closed abruptly"、HTTP 000）。
    只有 `curl_cffi` 的浏览器指纹（impersonate）能通 —— 缺库时脚本直接报错退出，不要退化。
    带东财 Cookie 可显著提高稳定性（实测 8/8 vs 4/8），故支持 `--cookie` / `EM_COOKIE` 环境变量；
    两者都没有时自动读同目录 `em_cookie.json`（由 `em_cookie.py --refresh/--ensure` 生成）。
    连续 burst 会被短时限流（表现为连接被重置），脚本内置退避重试。
★ 端点级风控（2026-09-24 实测，勿删 URLS 回退）：push2 的 `/api/qt/clist/get` 会被**路径级**定向 RST
    （curl 56 秒断），而同主机 `/api/qt/ulist.np/get` 正常、`push2test` 同路径正常返回同 schema 数据。
    故 `fetch` 按 `URLS` 顺序回退；两处主机都断才真失败。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    from curl_cffi import requests as creq
except ImportError:  # curl_cffi 是硬依赖，不可退化
    sys.exit("缺少 curl_cffi（pip install curl_cffi）—— push2 只能走浏览器指纹通道。")

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 主机按顺序尝试。★ 2026-09-24 实测：push2 存在**路径级**风控 ——
# `/api/qt/clist/get` 被定向 RST（curl 56，0.0s 秒断；PS/curl.exe/curl_cffi、HTTP1.1 与 h2 全断，
# 带不带 Cookie 都一样），而**同主机** `/api/qt/ulist.np/get` 却 200。
# `push2test` 主机同路径返回**同 schema** 的正常数据（total=504，字段一一对应），故作为回退。
# （`push2ex` 该路径 404、`push2delay` / `push2his` 同日实测同样被 RST，故不列入。）
URLS = (
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://push2test.eastmoney.com/api/qt/clist/get",
)

FIELDS = "f12,f14,f3,f4,f128,f140,f141,f136,f62"
BASE_PARAMS = {
    "pn": 1,
    "np": 1,
    "po": 1,          # 降序
    "fid": "f3",      # 按涨跌幅排序
    "fs": "m:90+t:3",  # 90=板块, t:3=概念板块
    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    "fltt": 2,
    "invt": 2,
    "fields": FIELDS,
}

# 浏览器指纹备选（按稳定性排序）；失败即换下一个
IMPERSONATES = ("chrome", "chrome136", "chrome120", "safari")
REFERER = "https://so.eastmoney.com/web/s?keyword=%E5%8D%8E%E8%8C%82%E8%82%A1%E4%BB%BD"

MARKET_NAME = {0: "深", 1: "沪"}


def fetch(limit: int = 10, cookie: str | None = None, retries: int = 2) -> dict:
    """拉取概念板块涨幅榜前 limit 名（多主机 × 多指纹依次尝试）。失败抛 RuntimeError。"""
    params = dict(BASE_PARAMS, pz=limit)
    headers = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": REFERER,
    }
    if cookie:
        headers["Cookie"] = cookie

    last_err = None
    for url in URLS:
        for imp in IMPERSONATES:
            for attempt in range(retries):
                try:
                    r = creq.get(url, params=params, headers=headers,
                                 impersonate=imp, timeout=15)
                    if r.status_code != 200:
                        last_err = f"{url} HTTP {r.status_code}"
                        time.sleep(1 + attempt)
                        continue
                    payload = r.json()
                    if not (payload.get("data") or {}).get("diff"):
                        # 200 但空榜：换指纹没用，直接换主机
                        last_err = f"{url} HTTP 200 但 data.diff 为空"
                        break
                    return payload
                except Exception as e:  # 连接被重置 / 超时
                    last_err = f"{url} {type(e).__name__}: {e}"
                    time.sleep(0.6 * (attempt + 1))
            # 换指纹前稍歇，避免连续 burst 被限流
            time.sleep(0.5)
    raise RuntimeError(f"push2 全部主机/指纹尝试失败（最后错误：{last_err}）")


def parse(payload: dict) -> list[dict]:
    """把 push2 返回体解析成行列表（保序）。"""
    data = payload.get("data") or {}
    rows = []
    for i, e in enumerate(data.get("diff") or [], 1):
        rows.append({
            "rank": i,
            "board_code": e.get("f12"),
            "board_name": e.get("f14"),
            "chg_pct": e.get("f3"),
            "chg_amt": e.get("f4"),
            "lead_name": e.get("f128"),
            "lead_code": e.get("f140"),
            "lead_market": e.get("f141"),
            "lead_market_name": MARKET_NAME.get(e.get("f141"), e.get("f141")),
            "lead_chg_pct": e.get("f136"),
            "lead_main_flow": e.get("f62"),
        })
    return rows


def fmt_pct(v) -> str:
    return "-" if v in (None, "-") else f"{v}%"


def render_markdown(rows: list[dict]) -> str:
    out = ["领涨概念", "", "| 序号 | 名称 | 涨跌幅 | 领涨股 |", "|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['rank']} | {r['board_name']} | {fmt_pct(r['chg_pct'])} | {r['lead_name']} |")
    return "\n".join(out)


def default_cookie() -> str | None:
    """Cookie 头取法：环境变量 EM_COOKIE 优先，其次 em_cookie.json（取不到返回 None）。"""
    env = (os.environ.get("EM_COOKIE") or "").strip()
    if env:
        return env
    try:
        import em_cookie
        return em_cookie.header(domain="eastmoney") or None
    except Exception:                              # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="东方财富「领涨概念」抓取")
    ap.add_argument("-n", "--limit", type=int, default=10, help="取前 N 名（默认 10）")
    ap.add_argument("--cookie", default=default_cookie(),
                    help="东财 Cookie（缺省：环境变量 EM_COOKIE → em_cookie.json；可留空）")
    ap.add_argument("--json", dest="json_path", help="将完整字段写入 JSON 文件")
    ap.add_argument("--csv", dest="csv_path", help="将完整字段写入 CSV 文件")
    args = ap.parse_args()

    payload = fetch(args.limit, args.cookie)
    rows = parse(payload)
    if not rows:
        print("未取到数据（data.diff 为空）", file=sys.stderr)
        return 1

    print(render_markdown(rows))

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump({"total": (payload.get("data") or {}).get("total"), "rows": rows},
                      f, ensure_ascii=False, indent=2)
        print(f"\n[JSON] {args.json_path}", file=sys.stderr)
    if args.csv_path:
        import csv
        with open(args.csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"[CSV] {args.csv_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
