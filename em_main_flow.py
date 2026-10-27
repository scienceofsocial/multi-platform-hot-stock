# -*- coding: utf-8 -*-
"""东方财富「主力净流入率」全市场抓取（独立新程序）。

说明
----
本文件是**新增**的独立脚本，不修改、不依赖任何既有程序的内部实现
（只读地借用同目录 `em_cookie.py` 的 cookie 能力，那是公共工具）。
`lianban_score.py` 等老程序保持原样，若有策略侧联动需求，另行新开文件。

指标口径
--------
    主力净流入率 = 主力净额占比(%) = 字段 f184
    定义：主力净流入额 / 当日成交额 × 100%；主力 = 超大单 + 大单。
    （与 https://data.eastmoney.com/zjlx/ 同源接口，横截面一次取全市场。）

字段映射（clist/get）
    f12 代码   f14 名称   f13 市场(0=深/1=沪)
    f2  最新价  f3  涨跌幅%
    f62 主力净额(元)
    f184 主力净额占比%   ← 本脚本要的「主力净流入率」

分组（fs）
    沪深主板/创业板/科创板 : m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23
    北交所                : m:0+t:81+s:2048

★ 分页（实测）：clist/get 的 pz 硬上限 = 100（pz=1000 仍只回 100 条），
  故取全市场必须按 pn 递增翻页，且需按分组分别翻。

★ 通道（照抄 em_lead_concept.py 的既有范式，勿退化）：
  push2 按 **TLS/HTTP 指纹** 做风控 —— `requests` / `httpx` / 系统 `curl.exe`
  一律被 RST，只有 `curl_cffi` 的浏览器指纹（impersonate）能通；缺库直接退出。
  带东财 Cookie 显著提高稳定性（实测 8/8 vs 4/8），故支持 `--cookie` /
  `EM_COOKIE` 环境变量，回落到同目录 `em_cookie.json`。
  push2 还存在**路径级**风控（`/api/qt/clist/get` 被定向 RST）时，回退
  `push2test` 同路径（返回同 schema），故 URLS 按顺序回退，两处都断才真失败。
  连续 burst 会被短时限流，故分页之间内置退避与间隔。

命令行
------
    python em_main_flow.py                     # 全市场按主力净流入率降序，打印前 30
    python em_main_flow.py -n 50               # 打印前 50
    python em_main_flow.py -n 0                # 打印全部
    python em_main_flow.py -p 5                # 只翻 5 页（快速抽样 / 调试）
    python em_main_flow.py --json _em_main_flow.json --csv _em_main_flow.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

try:
    from curl_cffi import requests as creq
except ImportError:  # curl_cffi 是硬依赖，不可退化为 requests
    sys.exit("缺少 curl_cffi（pip install curl_cffi）—— push2 只能走浏览器指纹通道。")

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))

# 主机按顺序回退：push2 存在路径级风控时换 push2test（同 schema）
URLS = (
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://push2test.eastmoney.com/api/qt/clist/get",
)

FIELDS = "f12,f14,f13,f2,f3,f62,f184"

BASE_PARAMS = {
    "np": 1,
    "po": 1,            # 降序
    "fid": "f184",      # 按「主力净流入率」排序
    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    "fltt": 2,
    "invt": 2,
    "fields": FIELDS,
}

# 分组：名称 -> fs。分开翻页后合并。
GROUPS = (
    ("沪深", "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"),
    ("北交所", "m:0+t:81+s:2048"),
)

PAGE_SIZE = 100  # pz 硬上限
IMPERSONATES = ("chrome", "chrome136", "chrome120", "safari")
REFERER = "https://data.eastmoney.com/zjlx/"
MARKET_NAME = {0: "深", 1: "沪"}

#: 上次成功的 (主机, 指纹)，翻页时优先复用（见 fetch_page 的「粘性通道」）
_STICKY: tuple[str, str] | None = None


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


def fetch_page(fs: str, pn: int, cookie: str | None, retries: int = 2) -> dict:
    """拉取某分组第 pn 页（100 条）。多主机 × 多指纹依次尝试，失败抛 RuntimeError。

    ★ 粘性通道：push2 常对 `/api/qt/clist/get` 做路径级 RST，若每页都从 URLS[0]
      开始重试，56 页会白白多花数倍时间。故把上次成功的 (url, impersonate)
      记住，下页优先复用；失败再退回完整回退链。
    """
    global _STICKY
    params = dict(BASE_PARAMS, fs=fs, pn=pn, pz=PAGE_SIZE)
    headers = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": REFERER,
    }
    if cookie:
        headers["Cookie"] = cookie

    combos = [(u, i) for u in URLS for i in IMPERSONATES]
    if _STICKY in combos:                      # 上次成功的通道优先
        combos = [_STICKY] + [c for c in combos if c != _STICKY]

    last_err = None
    for url, imp in combos:
        for attempt in range(retries):
            try:
                r = creq.get(url, params=params, headers=headers,
                             impersonate=imp, timeout=15)
                if r.status_code != 200:
                    last_err = f"{url} pn={pn} HTTP {r.status_code}"
                    time.sleep(1 + attempt)
                    continue
                payload = r.json()
                data = payload.get("data") or {}
                if pn == 1 and not data.get("diff"):
                    # 200 但空榜：换指纹没用，直接换主机
                    last_err = f"{url} pn={pn} HTTP 200 但 data.diff 为空"
                    break
                _STICKY = (url, imp)
                return payload
            except Exception as e:  # 连接被重置 / 超时
                last_err = f"{url} pn={pn} {type(e).__name__}: {e}"
                time.sleep(0.6 * (attempt + 1))
        time.sleep(0.4)  # 换通道前稍歇，避免连续 burst
    raise RuntimeError(f"push2 全部主机/指纹尝试失败（最后错误：{last_err}）")


def fetch_group(group: str, fs: str, cookie: str | None,
                max_pages: int = 0, sleep_s: float = 0.35) -> list[dict]:
    """翻页拉取一个分组的全部个股（max_pages=0 表示翻到底）。"""
    rows: list[dict] = []
    total = None
    pn = 1
    while True:
        payload = fetch_page(fs, pn, cookie)
        data = payload.get("data") or {}
        if total is None:
            total = int(data.get("total") or 0)
        diff = data.get("diff") or []
        if not diff:
            break
        for e in diff:
            rows.append({
                "group": group,
                "code": e.get("f12"),
                "name": e.get("f14"),
                "market": MARKET_NAME.get(e.get("f13"), e.get("f13")),
                "price": e.get("f2"),
                "chg_pct": e.get("f3"),
                "main_net": e.get("f62"),
                "main_net_pct": e.get("f184"),
            })
        print(f"  [{group}] pn={pn}/{((total or len(rows)) + PAGE_SIZE - 1) // PAGE_SIZE}"
              f" 已取 {len(rows)}/{total}", file=sys.stderr)
        if len(rows) >= total or (max_pages and pn >= max_pages):
            break
        pn += 1
        time.sleep(sleep_s)
    return rows


def fmt_yi(v) -> str:
    """主力净额（元）→ 亿元字符串。"""
    if not isinstance(v, (int, float)):
        return "-"
    return f"{v / 1e8:.2f}"


def fmt_pct(v) -> str:
    if not isinstance(v, (int, float)):
        return "-"
    return f"{v:.2f}%"


def render_markdown(rows: list[dict]) -> str:
    out = ["主力净流入率（东财 f184 = 主力净额占比%）", "",
           "| 序号 | 代码 | 名称 | 组 | 最新价 | 涨跌幅 | 主力净额(亿) | 主力净流入率 |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['rank']} | {r['code']} | {r['name']} | {r['group']} | "
                   f"{r['price']} | {fmt_pct(r['chg_pct'])} | {fmt_yi(r['main_net'])} | "
                   f"{fmt_pct(r['main_net_pct'])} |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="东方财富「主力净流入率」全市场抓取")
    ap.add_argument("-n", "--limit", type=int, default=30,
                    help="打印前 N 行（默认 30；0 = 全部）")
    ap.add_argument("-p", "--max-pages", type=int, default=0,
                    help="每分组最多翻几页（默认 0 = 翻到底；每页 100 条）")
    ap.add_argument("--sleep", type=float, default=0.35, help="分页间隔秒（默认 0.35）")
    ap.add_argument("--cookie", default=default_cookie(),
                    help="东财 Cookie（缺省：EM_COOKIE 环境变量 → em_cookie.json；可留空）")
    ap.add_argument("--json", dest="json_path", help="将完整字段写入 JSON 文件")
    ap.add_argument("--csv", dest="csv_path", help="将完整字段写入 CSV 文件")
    args = ap.parse_args()

    rows: list[dict] = []
    for group, fs in GROUPS:
        rows.extend(fetch_group(group, fs, args.cookie,
                                max_pages=args.max_pages, sleep_s=args.sleep))

    # 去重（按代码）后重排序：主力净流入率降序（"-" 或缺值排最后）
    seen: dict[str, dict] = {}
    for r in rows:
        seen.setdefault(str(r["code"]), r)
    rows = list(seen.values())

    def _key(r: dict):
        v = r["main_net_pct"]
        return (0, -v) if isinstance(v, (int, float)) else (1, 0.0)  # 缺值排最后

    rows.sort(key=_key)
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    if not rows:
        print("未取到数据（data.diff 为空）", file=sys.stderr)
        return 1

    show = rows if args.limit == 0 else rows[:args.limit]
    print(render_markdown(show))

    pos = sum(1 for r in rows if isinstance(r["main_net_pct"], (int, float))
              and r["main_net_pct"] > 0)
    by_group = {g: sum(1 for r in rows if r["group"] == g) for g, _ in GROUPS}
    print(f"\n覆盖 {len(rows)} 只（沪深 {by_group.get('沪深', 0)} / "
          f"北交所 {by_group.get('北交所', 0)}），主力净流入率为正 {pos} 只",
          file=sys.stderr)

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump({"count": len(rows), "rows": rows}, f,
                      ensure_ascii=False, indent=2)
        print(f"[JSON] {args.json_path}", file=sys.stderr)
    if args.csv_path:
        with open(args.csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"[CSV] {args.csv_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
