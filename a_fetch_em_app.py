# -*- coding: utf-8 -*-
"""东方财富 APP 侧「暗盘资金榜 / 板块 / 成份股 / 龙头」抓取。

★★ 独立产物，不改动五平台人气管线任何口径 ★★
    本脚本只读东财公开接口，产出 hot_em_concept.json / hot_em_concept.csv /
    hot_em_darkfund.csv 三个**新文件**；不读也不写 last_good.json，不参与
    a_duopingtai_hot_factor / a_export_tdx_hot_rank / a_report_daily 的任何打分。

===============================================================================
数据源
===============================================================================
[A] 暗盘资金榜  https://quotederivates.eastmoney.com/datacenter/darktrade
      入口页 https://emrnweb.eastmoney.com/graymarket/rankList
      sortflag=6 & desc=1  = 暗盘资金降序（唯一可用）
[B] 板块（地域/行业/概念）  https://push2.eastmoney.com/api/qt/clist/get
      fs=m:90+t:1(地域 31) / t:2(行业 496) / t:3(概念 504)
[C] 成份股  fs=b:BKxxxx（同一 push2 端点，fid=f62 按主力净流入降序）
[D] 人气榜  https://emappdata.eastmoney.com/stockrank/getAllCurrentList（POST）

===============================================================================
字段语义（探针 _probe_em13/15/20/21/22/23/24 实测逐字确认）
===============================================================================
push2 板块行
    f12 板块代码(BKxxxx)  f14 板块名称  f2 板块点位  f3 涨跌幅%
    f62 主力净流入(元)    f104 涨家数    f105 跌家数
    f128/f140/f141 = 领涨股（涨幅第一）名称/代码/市场(0深 1沪)   ← 网页「领涨概念」榜同源
    f204/f205/f206 = 领涨龙（**主力净流入第一**）名称/代码/市场   ← 与领涨股是两回事
    f207/f208      = 跌幅龙 名称/代码
    f209 板块标记  f210 "-"
    （f257 = 5日主力净流入第一 / f260 = 10日主力净流入第一，本脚本暂不落库）
push2 成份股行
    f104~f210 全为 "-"，只有 f2(价) / f3(涨幅%) / f6(成交额,元) / f62(主力净流入,元) 有值
暗盘榜（键是字符串数字）
    "3"市场(1沪/0深) "4"代码 "5"内码 "6"暗盘资金 "7"明盘资金 "8"主力净流入(="6"+"7")
    "11"活跃度 "13"价格×1000 "14"涨跌幅(小数) "16"名称 "21"真名次   —— 资金单位 = 元
    恒等式（实测）：dark_fund("6") + open_fund("7") == main_net_inflow("8")
人气榜
    {"data":[{"sc":"SZ002119","rk":1,...}]}  → sc 恒为 SH/SZ/BJ 前缀

===============================================================================
通道要点 / 踩坑（勿改回）
===============================================================================
* push2 有 **TLS 指纹风控**：requests / httpx / 系统 curl.exe(Schannel) / 裸 socket
  一律被 RST，**只有 curl_cffi 的浏览器指纹能通**；带东财 Cookie 显著提高稳定性
  （实测 8/8 vs 4/8）。故建会话时挂伪 ct/ut cookie，并轮换 impersonate 指纹。
* 暗盘域 **无 TLS 风控**（纯 requests 亦通），但**编码必须是 UTF-8**，非 GBK
  （_probe_em13 实测 gbk 解码抛 UnicodeDecodeError）→ load_json_utf8() UTF-8 优先。
* 暗盘榜 sortflag=4 / "1" 返回**同一份静态序**、字段 "21" 非单调 —— **不要用**。
* 暗盘榜 NumPerPage 上限 **100**（>100 返回 0 行）；全市场约 5.3k 只 → 约 54 页。
* 人气榜 pageSize 上限 **100**，pageNo>1 返回空 —— 只能拿全市场前 100 名。
  「人气龙」APP 板块页为自绘标签、**无公开字段**，本脚本用**代理口径**：
  板块内成份股中人气榜 rk 最小者。
* 主流程顺序必须是 [D]人气榜 → [A]暗盘榜 → [B]板块 → [C]成份股+龙头标注，
  否则板块级「人气龙」无从计算。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))

JSON_NAME = "hot_em_concept.json"
CSV_NAME = "hot_em_concept.csv"
DARK_CSV_NAME = "hot_em_darkfund.csv"

UT = "bd1d9ddb04089700cf9c27f6f7426281"
PUSH2 = "https://push2.eastmoney.com/api/qt/clist/get"
DARK_URL = "https://quotederivates.eastmoney.com/datacenter/darktrade"
POP_URL = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

PUSH2_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://quote.eastmoney.com/",
}
DARK_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://emrnweb.eastmoney.com/graymarket/rankList",
    "rnProjectId": "emrn.GrayMarketRank",          # 必带，缺则 4xx
}
POP_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://vipmoney.eastmoney.com",
    "Referer": "https://vipmoney.eastmoney.com/",
}
FAKE_COOKIES = {"ct": "zzzz", "ut": "zzzz"}

# 浏览器指纹备选（按稳定性排序）；失败即换下一个
IMPERSONATES = ("chrome", "chrome136", "chrome120", "safari")

DARK_PAGE_SIZE = 100
DARK_LOOKBACK_DAYS = 10                            # 从今天起回溯找有数据的日期

BOARD_FIELDS = ("f12,f14,f2,f3,f62,f104,f105,f128,f140,f141,"
                "f204,f205,f206,f207,f208,f209,f210")
STOCK_FIELDS = "f12,f13,f14,f2,f3,f6,f62"          # f13 = 市场(0深 1沪)

BOARD_TYPES = (
    ("1", "region", "地域板块"),
    ("2", "industry", "行业板块"),
    ("3", "concept", "概念板块"),
)
BOARD_TYPE_ALIAS = {"region": "1", "industry": "2", "concept": "3",
                    "1": "1", "2": "2", "3": "3", "地域": "1", "行业": "2", "概念": "3"}

BOARD_PAGE_SIZE = 600
STOCK_PAGE_SIZE = 100

POP_BODY = {"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38",
            "marketType": "", "pageNo": 1, "pageSize": 100}

DEFAULT_SLEEP = 0.12
RETRY = 3

DARK_CSV_COLUMNS = ["rank", "code", "name", "sc", "market", "dark_fund", "open_fund",
                    "main_net_inflow", "activity", "price", "chg_pct"]
STOCK_CSV_COLUMNS = ["board_type", "board_type_name", "board_code", "board_name",
                     "board_chg_pct", "board_main_net_inflow", "stock_rank", "code",
                     "name", "sc", "price", "chg_pct", "amount", "main_net_inflow",
                     "is_lead_stock", "is_dragon", "pop_rank", "is_pop_dragon"]

_SESSION = None
_ENGINE = None
_IMP_IDX = 0
_SLEEP = DEFAULT_SLEEP
_WARNED: set[str] = set()


# ---------------------------------------------------------------- 基础设施

def warn(tag: str, msg: str) -> None:
    """同一 tag 只播报一次，避免刷屏。"""
    if tag in _WARNED:
        return
    _WARNED.add(tag)
    print(f"  [warn] {msg}")


def _inject_cookies(session) -> int:
    """注入东财真实 cookie（em_cookie.ensure：缺失/过期自动刷新；失败退化为读文件）。

    取不到任何 cookie 时返回 0，由调用方退回伪 ct/ut。
    """
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        import em_cookie
    except Exception:                              # noqa: BLE001
        return 0
    try:
        jar = em_cookie.ensure(verbose=False)
    except Exception:                              # noqa: BLE001
        jar = em_cookie.load()
    if not jar:
        return 0
    try:
        return em_cookie.apply(session, jar)
    except Exception:                              # noqa: BLE001
        return 0


def build_session():
    """建会话：curl_cffi 浏览器指纹 + 东财真实 cookie；缺库退化为 requests（push2 会失败）。"""
    global _SESSION, _ENGINE
    if _SESSION is not None:
        return _SESSION
    try:
        from curl_cffi import requests as creq
        s = creq.Session(impersonate=IMPERSONATES[0])
        _ENGINE = "curl_cffi"
    except ImportError:
        import requests as creq
        s = creq.Session()
        _ENGINE = "requests"
        warn("no-curl-cffi",
             "缺 curl_cffi（pip install curl_cffi）—— push2 有 TLS 风控，本引擎大概率全失败。")
    n = _inject_cookies(s)
    if n:
        print(f"  已注入东财真实 cookie {n} 个（em_cookie.json）")
    else:
        for k, v in FAKE_COOKIES.items():
            try:
                s.cookies.set(k, v, domain=".eastmoney.com")
            except Exception:                      # noqa: BLE001
                s.cookies.set(k, v)
        warn("fake-cookie",
             "无 em_cookie.json（或提取失败）—— 退回伪 ct/ut cookie，push2 成功率会下降。")
    _SESSION = s
    return s


def _rotate_impersonate() -> None:
    """换一个浏览器指纹（curl_cffi 会话支持 set_impersonate）。"""
    global _IMP_IDX
    if _ENGINE != "curl_cffi":
        return
    _IMP_IDX = (_IMP_IDX + 1) % len(IMPERSONATES)
    try:
        _SESSION.impersonate = IMPERSONATES[_IMP_IDX]
    except Exception:                              # noqa: BLE001
        pass


def http_get(url: str, params: dict, headers: dict, retries: int = RETRY):
    """GET 并返回原始 bytes；失败抛 RuntimeError。"""
    s = build_session()
    last = None
    for attempt in range(retries):
        try:
            r = s.get(url, params=params, headers=headers, timeout=25)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}"
                time.sleep(1 + attempt)
                continue
            return r.content
        except Exception as e:                     # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.2 * (attempt + 1))
        _rotate_impersonate()
    raise RuntimeError(f"GET 失败 {url} （最后错误：{last}）")


def http_post_json(url: str, body: dict, headers: dict, retries: int = RETRY):
    """POST JSON 并返回原始 bytes；失败抛 RuntimeError。"""
    s = build_session()
    last = None
    for attempt in range(retries):
        try:
            r = s.post(url, json=body, headers=headers, timeout=25)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}"
                time.sleep(1 + attempt)
                continue
            return r.content
        except Exception as e:                     # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.2 * (attempt + 1))
        _rotate_impersonate()
    raise RuntimeError(f"POST 失败 {url} （最后错误：{last}）")


def load_json_bytes(raw: bytes):
    """UTF-8 优先、GBK 兜底（暗盘域实测 UTF-8；gbk 会因多字节越界而失败）。"""
    for enc in ("utf-8", "gbk"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:                          # noqa: BLE001
            continue
    raise ValueError("响应既非 UTF-8 也非 GBK 可解析的 JSON")


def pace() -> None:
    if _SLEEP > 0:
        time.sleep(_SLEEP)


def to_float(v, default=None):
    if v is None or v == "-" or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def to_int(v, default=None):
    f = to_float(v)
    return default if f is None else int(f)


def is_dash(v) -> bool:
    return v is None or v == "-" or v == ""


def to_sc(market, code: str) -> str:
    """拼 SH/SZ/BJ 前缀；市场号优先，缺失时按号段推断。"""
    code = (code or "").strip()
    if not code:
        return ""
    if market in (0, "0"):
        return "SZ" + code
    if market in (1, "1"):
        return "SH" + code
    if market in (2, "2"):
        return "BJ" + code
    if code[0] == "6":
        return "SH" + code
    if code[0] in ("0", "3"):
        return "SZ" + code
    if code[0] in ("4", "8", "9"):
        return "BJ" + code
    return code


def save_json_atomic(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def save_csv_atomic(path: str, columns: list[str], rows: list[dict]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


# ---------------------------------------------------------------- [A] 暗盘资金榜

def norm_dark_row(it: dict) -> dict:
    code = (it.get("4") or "").strip()
    market = to_int(it.get("3"))
    px = to_float(it.get("13"))
    chg = to_float(it.get("14"))
    return {
        "rank": to_int(it.get("21")),
        "code": code,
        "name": it.get("16"),
        "market": market,
        "sc": to_sc(market, code),
        "dark_fund": to_float(it.get("6")),
        "open_fund": to_float(it.get("7")),
        "main_net_inflow": to_float(it.get("8")),
        "activity": to_float(it.get("11")),
        "price": None if px is None else round(px / 1000.0, 3),
        "chg_pct": None if chg is None else round(chg * 100.0, 3),
    }


def fetch_dark_page(date_str: str, page: int, size: int = DARK_PAGE_SIZE) -> dict:
    params = {"version": 101, "cver": 100, "date": date_str, "StartPage": page,
              "NumPerPage": size, "sortflag": 6, "desc": 1, "market": "", "datetype": ""}
    return load_json_bytes(http_get(DARK_URL, params, DARK_HEADERS))


def fetch_dark_rank(want_date: str | None, max_pages: int) -> dict:
    """拉暗盘资金榜。未指定日期时从今天起回溯最多 DARK_LOOKBACK_DAYS 天找有数据的日期。"""
    if want_date:
        cands = [want_date]
    else:
        today = date.today()
        cands = [(today - timedelta(days=i)).strftime("%Y%m%d")
                 for i in range(DARK_LOOKBACK_DAYS)]

    for ds in cands:
        try:
            head = fetch_dark_page(ds, 1)
        except RuntimeError as e:
            warn("dark-first", f"暗盘榜第 1 页失败：{e}")
            continue
        rows = head.get("data") or []
        total = to_int(head.get("2"), 0) or 0
        if not rows:
            continue
        pages = max(1, -(-total // DARK_PAGE_SIZE))
        if max_pages > 0:
            pages = min(pages, max_pages)
        out = [norm_dark_row(x) for x in rows]
        for pn in range(2, pages + 1):
            pace()
            page = fetch_dark_page(ds, pn)
            out.extend(norm_dark_row(x) for x in (page.get("data") or []))
        return {"date": ds, "total": total, "pages_fetched": pages,
                "rows_fetched": len(out), "rows": out}
    return {"date": None, "total": 0, "pages_fetched": 0, "rows_fetched": 0, "rows": []}


# ---------------------------------------------------------------- [D] 人气榜

def fetch_pop_rank_map() -> dict[str, int]:
    """全市场人气榜 top100 → {sc: rk}（pageSize 上限 100，取不到更多）。"""
    raw = http_post_json(POP_URL, POP_BODY, POP_HEADERS)
    j = load_json_bytes(raw)
    out: dict[str, int] = {}
    for it in j.get("data") or []:
        sc = (it.get("sc") or "").strip().upper()
        rk = to_int(it.get("rk"))
        if sc and rk is not None:
            out[sc] = rk
    return out


# ---------------------------------------------------------------- [B] 板块

def pick_pop_dragon(stocks: list[dict], pop_map: dict[str, int]):
    """板块内人气榜名次最小者（代理「人气龙」）；无人上榜返回 None。"""
    best = None
    for s in stocks:
        rk = pop_map.get(s.get("sc") or "")
        if rk is None:
            continue
        if best is None or rk < best[1]:
            best = (s, rk)
    if best is None:
        return None, None
    s, rk = best
    return {"code": s.get("code"), "name": s.get("name"), "sc": s.get("sc"), "rank": rk}, rk


def norm_board_row(it: dict, type_key: str, type_name: str) -> dict:
    lead_code = (it.get("f140") or "").strip() if not is_dash(it.get("f140")) else ""
    lead_mkt = it.get("f141")
    drag_code = (it.get("f205") or "").strip() if not is_dash(it.get("f205")) else ""
    drag_mkt = it.get("f206")
    down_code = (it.get("f208") or "").strip() if not is_dash(it.get("f208")) else ""
    lead = None
    if not is_dash(it.get("f128")) or lead_code:
        lead = {"name": None if is_dash(it.get("f128")) else it.get("f128"),
                "code": lead_code or None,
                "market": to_int(lead_mkt),
                "sc": to_sc(to_int(lead_mkt), lead_code) if lead_code else None}
    dragon = None
    if not is_dash(it.get("f204")) or drag_code:
        dragon = {"name": None if is_dash(it.get("f204")) else it.get("f204"),
                  "code": drag_code or None,
                  "market": to_int(drag_mkt),
                  "sc": to_sc(to_int(drag_mkt), drag_code) if drag_code else None}
    down_dragon = None
    if not is_dash(it.get("f207")) or down_code:
        down_dragon = {"name": None if is_dash(it.get("f207")) else it.get("f207"),
                       "code": down_code or None,
                       "sc": to_sc(None, down_code) if down_code else None}
    return {
        "type": type_key,
        "type_name": type_name,
        "board_code": it.get("f12"),
        "board_name": it.get("f14"),
        "price": to_float(it.get("f2")),
        "chg_pct": to_float(it.get("f3")),
        "main_net_inflow": to_float(it.get("f62")),
        "up_count": to_int(it.get("f104")),
        "down_count": to_int(it.get("f105")),
        "lead_stock": lead,                         # f128/f140/f141 领涨股（涨幅第一）
        "dragon_stock": dragon,                     # f204/f205/f206 领涨龙（主力净流入第一）
        "down_dragon": down_dragon,                 # f207/f208 跌幅龙
        "pop_dragon": None,                         # 人气龙（代理，成份股取回后填）
        "stock_count": None,
        "stocks": [],
    }


def fetch_boards(type_key: str, type_name: str, t: str, limit: int) -> list[dict]:
    params = {"pn": 1, "pz": BOARD_PAGE_SIZE, "po": 1, "np": 1, "fltt": 2, "invt": 2,
              "fid": "f3", "fs": f"m:90+t:{t}", "fields": BOARD_FIELDS, "ut": UT}
    j = load_json_bytes(http_get(PUSH2, params, PUSH2_HEADERS))
    data = j.get("data") or {}
    diff = data.get("diff") or []
    total = to_int(data.get("total"), 0) or 0
    out = [norm_board_row(x, type_key, type_name) for x in diff]

    pn = 2
    while len(diff) < total and len(out) < (limit or 10 ** 9):
        if BOARD_PAGE_SIZE * (pn - 1) >= total:
            break
        params["pn"] = pn
        pace()
        page = load_json_bytes(http_get(PUSH2, params, PUSH2_HEADERS))
        d2 = (page.get("data") or {}).get("diff") or []
        if not d2:
            break
        out.extend(norm_board_row(x, type_key, type_name) for x in d2)
        diff = d2
        pn += 1

    if limit > 0:
        out = out[:limit]
    return out


# ---------------------------------------------------------------- [C] 成份股

def norm_stock_row(it: dict, rank_no: int) -> dict:
    code = (it.get("f12") or "").strip()
    market = to_int(it.get("f13"))
    return {
        "stock_rank": rank_no,
        "code": code,
        "name": it.get("f14"),
        "market": market,
        "sc": to_sc(market, code),
        "price": to_float(it.get("f2")),
        "chg_pct": to_float(it.get("f3")),
        "amount": to_float(it.get("f6")),
        "main_net_inflow": to_float(it.get("f62")),
        "is_lead_stock": False,
        "is_dragon": False,
        "pop_rank": None,
        "is_pop_dragon": False,
    }


def fetch_constituents(board_code: str, limit: int) -> list[dict]:
    params = {"pn": 1, "pz": STOCK_PAGE_SIZE, "po": 1, "np": 1, "fltt": 2, "invt": 2,
              "fid": "f62", "fs": f"b:{board_code}", "fields": STOCK_FIELDS, "ut": UT}
    j = load_json_bytes(http_get(PUSH2, params, PUSH2_HEADERS))
    data = j.get("data") or {}
    diff = data.get("diff") or []
    total = to_int(data.get("total"), 0) or 0
    out = [norm_stock_row(x, i) for i, x in enumerate(diff, 1)]

    pn = 2
    while len(diff) < total and (limit <= 0 or len(out) < limit):
        params["pn"] = pn
        pace()
        page = load_json_bytes(http_get(PUSH2, params, PUSH2_HEADERS))
        d2 = (page.get("data") or {}).get("diff") or []
        if not d2:
            break
        base = len(out)
        out.extend(norm_stock_row(x, base + i) for i, x in enumerate(d2, 1))
        diff = d2
        pn += 1

    if limit > 0:
        out = out[:limit]
    return out


def annotate_board(board: dict, pop_map: dict[str, int]) -> None:
    """给板块贴龙头标记：领涨股 / 领涨龙 / 人气龙（代理）。"""
    lead = board.get("lead_stock") or {}
    dragon = board.get("dragon_stock") or {}
    lead_code = lead.get("code")
    dragon_code = dragon.get("code")
    for s in board["stocks"]:
        s["is_lead_stock"] = bool(lead_code) and s["code"] == lead_code
        s["is_dragon"] = bool(dragon_code) and s["code"] == dragon_code
        s["pop_rank"] = pop_map.get(s.get("sc") or "")
    pd, _ = pick_pop_dragon(board["stocks"], pop_map)
    board["pop_dragon"] = pd
    for s in board["stocks"]:
        s["is_pop_dragon"] = bool(pd) and s["code"] == pd["code"]
    board["stock_count"] = len(board["stocks"])


# ---------------------------------------------------------------- 主流程

def parse_date(s: str) -> str:
    s = s.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"日期格式不支持：{s}（用 YYYYMMDD 或 YYYY-MM-DD）")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="东方财富 APP 侧 暗盘资金榜 / 板块 / 成份股 / 龙头 抓取")
    ap.add_argument("--date", type=parse_date, default=None,
                    help="暗盘榜日期（YYYYMMDD 或 YYYY-MM-DD）；缺省从今天起回溯最多 10 天")
    ap.add_argument("--types", default="region,industry,concept",
                    help="板块类型，逗号分隔：region/industry/concept（默认三类全取）")
    ap.add_argument("--limit-boards", type=int, default=0, help="每类板块最多取几个（0=全部）")
    ap.add_argument("--limit-stocks", type=int, default=0, help="每个板块最多取几只成份股（0=全部）")
    ap.add_argument("--dark-max-pages", type=int, default=0, help="暗盘榜最多翻几页（0=全部）")
    ap.add_argument("--no-dark", action="store_true", help="跳过暗盘榜")
    ap.add_argument("--no-board", action="store_true", help="跳过板块与成份股")
    ap.add_argument("--sleep", type=float, default=DEFAULT_SLEEP, help="每次请求之间的间隔秒（默认 0.12）")
    ap.add_argument("--json", dest="json_path", default=None, help=f"主产物路径（默认 {JSON_NAME}）")
    ap.add_argument("--csv", dest="csv_path", default=None, help=f"板块-成份股 CSV（默认 {CSV_NAME}）")
    ap.add_argument("--dark-csv", dest="dark_csv_path", default=None,
                    help=f"暗盘榜 CSV（默认 {DARK_CSV_NAME}）")
    return ap


def run(args) -> int:
    global _SLEEP
    _SLEEP = max(0.0, args.sleep)

    json_path = args.json_path or os.path.join(HERE, JSON_NAME)
    csv_path = args.csv_path or os.path.join(HERE, CSV_NAME)
    dark_csv_path = args.dark_csv_path or os.path.join(HERE, DARK_CSV_NAME)

    t0 = time.time()
    print("=" * 78)
    print(f"东财 APP 侧抓取  engine={build_session().__class__.__module__}"
          f"  日期入参={args.date or '自动回溯'}  sleep={_SLEEP}")

    # [D] 人气榜（必须先取，供板块级「人气龙」代理）
    pop_map: dict[str, int] = {}
    if not (args.no_dark and args.no_board):
        print("[D] 人气榜 top100 …")
        try:
            pop_map = fetch_pop_rank_map()
            print(f"    命中 {len(pop_map)} 只"
                  + (f"  榜首={min(pop_map, key=pop_map.get)}" if pop_map else ""))
        except Exception as e:                     # noqa: BLE001
            print(f"    [warn] 人气榜失败（人气龙将全为空）：{type(e).__name__}: {e}")

    # [A] 暗盘资金榜
    dark = {"date": None, "total": 0, "pages_fetched": 0, "rows_fetched": 0, "rows": []}
    if not args.no_dark:
        print("[A] 暗盘资金榜 …")
        try:
            dark = fetch_dark_rank(args.date, args.dark_max_pages)
            if dark["date"]:
                print(f"    date={dark['date']} total={dark['total']} "
                      f"pages={dark['pages_fetched']} rows={dark['rows_fetched']}")
                bad = [r for r in dark["rows"]
                       if r["dark_fund"] is not None and r["open_fund"] is not None
                       and r["main_net_inflow"] is not None
                       and abs((r["dark_fund"] + r["open_fund"]) - r["main_net_inflow"]) > 1]
                print(f"    恒等式 暗盘+明盘=主力净流入 校验：违例 {len(bad)} 行")
            else:
                print("    [warn] 回溯 %d 天均无数据" % DARK_LOOKBACK_DAYS)
        except Exception as e:                     # noqa: BLE001
            print(f"    [warn] 暗盘榜失败：{type(e).__name__}: {e}")

    # [B]+[C] 板块与成份股
    boards: list[dict] = []
    if not args.no_board:
        wanted = [x.strip() for x in (args.types or "").split(",") if x.strip()]
        picked = []
        for w in wanted:
            t = BOARD_TYPE_ALIAS.get(w)
            if not t:
                warn("bad-type", f"--types 含无法识别的项：{w}")
                continue
            nm = {"1": "地域板块", "2": "行业板块", "3": "概念板块"}[t]
            key = {"1": "region", "2": "industry", "3": "concept"}[t]
            picked.append((key, nm, t))

        for key, nm, t in picked:
            print(f"[B] {nm}（t:{t}）…")
            try:
                bs = fetch_boards(key, nm, t, args.limit_boards)
            except Exception as e:                 # noqa: BLE001
                print(f"    [warn] 板块拉取失败：{type(e).__name__}: {e}")
                continue
            print(f"    板块 {len(bs)} 个")
            for i, b in enumerate(bs, 1):
                try:
                    b["stocks"] = fetch_constituents(b["board_code"], args.limit_stocks)
                    annotate_board(b, pop_map)
                except Exception as e:             # noqa: BLE001
                    print(f"    [warn] {b['board_code']} {b['board_name']} 成份股失败："
                          f"{type(e).__name__}: {e}")
                if i % 25 == 0 or i == len(bs):
                    print(f"    [C] {nm} {i}/{len(bs)} … {b['board_name']}"
                          f" 成份 {b['stock_count']}")
            boards.extend(bs)

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "eastmoney-app (darktrade + push2 clist + stockrank)",
        "note": "独立产物，不改动五平台人气管线任何口径",
        "pop": {"count": len(pop_map), "map": pop_map},
        "dark": dark,
        "boards": boards,
    }

    save_json_atomic(json_path, payload)
    print(f"[JSON] {json_path}  ({len(boards)} 板块 / {dark['rows_fetched']} 暗盘行)")

    if dark["rows"]:
        save_csv_atomic(dark_csv_path, DARK_CSV_COLUMNS, dark["rows"])
        print(f"[CSV ] {dark_csv_path}  ({len(dark['rows'])} 行)")

    detail_rows: list[dict] = []
    for b in boards:
        for s in b["stocks"]:
            r = dict(s)
            r.update({"board_type": b["type"], "board_type_name": b["type_name"],
                      "board_code": b["board_code"], "board_name": b["board_name"],
                      "board_chg_pct": b["chg_pct"],
                      "board_main_net_inflow": b["main_net_inflow"]})
            detail_rows.append(r)
    if detail_rows:
        save_csv_atomic(csv_path, STOCK_CSV_COLUMNS, detail_rows)
        print(f"[CSV ] {csv_path}  ({len(detail_rows)} 行)")

    print(f"耗时 {time.time() - t0:.1f}s")
    print("=" * 78)
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                              # noqa: BLE001
        pass
    args = build_parser().parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
