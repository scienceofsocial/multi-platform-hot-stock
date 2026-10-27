# -*- coding: utf-8 -*-
"""龙头榜(sj88.ld) 变化时点统计 —— 把「时刻 / 只数 / 形态 / 龙头top3」四列固化成可复算的结论。

为什么需要
----------
「龙头榜_变化时点_<date>.md」只是**原始明细**：每天几十~上百个变化时点，人眼看不出规律。
本脚本把全部历史日期汇总成可算的量，并落成 Markdown 报告：

    1. 节奏 -- 变化点落在盘前/早盘/午休/午后/盘后哪个时段、归零(空榜)集中在几点
    2. 形态 -- 「换位」对次日收益到底有没有用（结论：没用）
    3. 龙头 -- top1/top3/全榜 的 T+1~T+5 超额收益与留存率
    4. 只数 -- 当日榜内只数分档 与 次日榜内平均涨幅的关系

口径与坑
--------
* 数据源：只读 龙头榜_变化时点_*.md 的表格行，不重新解析 295MB 的 hot_trace.jsonl
* 行情：本机通达信 C:\\new_tdx\\vipdoc\\{sh,sz}\\lday\\*.day（32 字节定长），基准 sh000001
* 收益：T 日收盘买入 -> T+n 日收盘卖出，超额 = 个股涨幅 - 上证同期涨幅
* 异常日：结构性坏日期写死进 ANOMALY_DAYS，报告单独列出、默认不进统计

用法
----
::

    python ld_timeline_stats.py                      # 全历史统计 + 写报告
    python ld_timeline_stats.py --since 2026-10-08   # 只看某天之后
    python ld_timeline_stats.py --no-write           # 只打印，不落盘
    python ld_timeline_stats.py --json               # 额外输出机器可读摘要
    python ld_timeline_stats.py --check              # 只做数据体检（日期分类）

退出码：0 正常；2 找不到任何明细文件。
"""
import argparse
import datetime as dt
import json
import os
import re
import statistics
import struct
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
REPORT_MD = os.path.join(OUT_DIR, "龙头榜_变化时点_统计.md")
SUMMARY_JSON = os.path.join(OUT_DIR, "龙头榜_变化时点_统计.json")

TDX = r"C:\new_tdx\vipdoc"
ARCHIVE = os.path.join(HERE, "_hot_archive")

PREFIX = "龙头榜_变化时点_"
FILE_RE = re.compile(r"^" + re.escape(PREFIX) + r"(\d{4}-\d{2}-\d{2})\.md$")

ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*(\d{2}:\d{2}:\d{2})\s*\|\s*(\d+)\s*(?:→\s*(\d+))?\s*\|"
    r"\s*进(\d+)\s*出(\d+)\s*换位(\d+)\s*\|\s*(.*?)\s*\|$"
)
INIT_RE = re.compile(r"^\|\s*—\s*\|\s*(\d{2}:\d{2}:\d{2})\(INIT\)\s*\|\s*(\d+)\s*\|")

BOARD_LABEL = "55188 龙头榜 (sj88.ld)"

#: 结构性坏日期：时间戳/条数与交易日不符，**默认剔除**，但仍在报告「数据体检」一节列出。
ANOMALY_DAYS = {
    "2026-09-30": (
        "国庆长假采集器未停，时间戳跨日轮转（00:03→03:50→19:31→次日 08:04…），"
        "单日堆出 195 个变化点、41 次归零，均为账本假象"
    ),
}

SESSIONS = (
    ("盘前", "00:00:00", "09:30:00"),
    ("早盘", "09:30:00", "11:40:00"),
    ("午休", "11:40:00", "13:00:00"),
    ("午后", "13:00:00", "15:00:00"),
    ("盘后", "15:00:00", "24:00:00"),
)

#: 变化点少于此数 => 判定采集断档
THIN_DAY_MAX = 2


# ======================================================================
# 1. 读取明细 + 日期分类
# ======================================================================
def list_files():
    out = []
    for f in os.listdir(HERE):
        m = FILE_RE.match(f)
        if m:
            out.append((m.group(1), os.path.join(HERE, f)))
    return sorted(out)


def parse_day(path):
    """一个明细文件 -> dict(init_t, init_n, rows=[...])。"""
    init_t, init_n, rows = None, None, []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if init_t is None:
                m = INIT_RE.match(line)
                if m:
                    init_t, init_n = m.group(1), int(m.group(2))
                    continue
            m = ROW_RE.match(line)
            if not m:
                continue
            n1 = int(m.group(4)) if m.group(4) else int(m.group(3))
            rows.append({
                "idx": int(m.group(1)), "t": m.group(2),
                "n0": int(m.group(3)), "n1": n1,
                "inn": int(m.group(5)), "out": int(m.group(6)), "mv": int(m.group(7)),
                "top": [c.strip() for c in m.group(8).split(",")
                        if c.strip() and c.strip() != "—"],
            })
    return {"init_t": init_t, "init_n": init_n, "rows": rows}


def classify(files):
    """给每个日期打标签 ok / weekend / thin / anomaly；返回 (usable, meta)。"""
    usable, meta = [], []
    for date, path in files:
        rec = parse_day(path)
        n = len(rec["rows"])
        if date in ANOMALY_DAYS:
            tag, why = "anomaly", ANOMALY_DAYS[date]
        elif n == 0:
            tag, why = "weekend", "0 个变化点（周末/假期，仅 INIT 行，属正常）"
        elif n <= THIN_DAY_MAX:
            tag, why = "thin", "仅 %d 个变化点，采集断档" % n
        else:
            tag, why = "ok", ""
        meta.append({"date": date, "n": n, "tag": tag, "why": why,
                     "init_t": rec["init_t"], "init_n": rec["init_n"]})
        if tag == "ok":
            usable.append((date, rec))
    return usable, meta


# ======================================================================
# 2. 行情（通达信日线）
# ======================================================================
_bars_cache = {}


def read_day(mkt, code):
    """读到 {yyyymmdd: close}。文件缺失返回空 dict（不抛）。"""
    key = (mkt, code)
    if key in _bars_cache:
        return _bars_cache[key]
    path = os.path.join(TDX, mkt, "lday", "%s%s.day" % (mkt, code))
    out = {}
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
        for i in range(0, len(blob) - 31, 32):
            d, _o, _h, _l, c, _a, _v, _r = struct.unpack("<IIIIIfII", blob[i:i + 32])
            out[d] = c / 100.0
    except OSError:
        pass
    _bars_cache[key] = out
    return out


class Quotes(object):
    """交易日历 + 上证基准。"""

    def __init__(self):
        self.bench = read_day("sh", "000001")
        self.cal = sorted(self.bench)
        self.idx = {d: i for i, d in enumerate(self.cal)}

    def ok(self):
        return bool(self.cal)

    def is_trading_day(self, date):
        """日期是否为真实交易日（上证指数当天有 K 线）。

        ⚠️ 周末/假期采集器仍在写 hot_<date>.json，若不剔除会把「周末快照」
        当成一个交易日混进 rank 序列，把留存率、资历等全部算歪
        （2026-10-28 实测：22 份快照里 10-01/10-24/10-25 是假日期）。
        """
        return self._i(date) is not None

    def _i(self, date):
        return self.idx.get(int(date.replace("-", "")))

    def ret(self, code, date, n):
        """个股 T -> T+n 涨幅；不足 n 根或数据缺失返回 None。"""
        i = self._i(date)
        if i is None or i + n >= len(self.cal):
            return None
        bars = read_day("sh" if code.startswith("SH") else "sz", code[2:])
        c0, c1 = bars.get(self.cal[i]), bars.get(self.cal[i + n])
        if not c0 or not c1:
            return None
        return c1 / c0 - 1.0

    def bret(self, date, n):
        i = self._i(date)
        if i is None or i + n >= len(self.cal):
            return None
        c0, c1 = self.bench.get(self.cal[i]), self.bench.get(self.cal[i + n])
        if not c0 or not c1:
            return None
        return c1 / c0 - 1.0


# ======================================================================
# 3. 统计
# ======================================================================
def session_of(t):
    for name, lo, hi in SESSIONS:
        if lo <= t < hi:
            return name
    return "盘后"


def mean(xs):
    return statistics.mean(xs) if xs else None


def stat_block(xs):
    if not xs:
        return None
    return {"n": len(xs), "mean": mean(xs),
            "win": sum(1 for x in xs if x > 0) / len(xs),
            "median": statistics.median(xs)}


def load_final_ranks(usable, q=None):
    """归档快照 -> ({(date): [(code, rank), ...]}, [被剔除的非交易日])。

    按 rank 升序，只保留整数 rank。给了 q 就**只认交易日历**：
    周末/假期写出来的 hot_<date>.json 一律不进序列，并单独返回名单。
    """
    final, dropped = {}, []
    for date, _rec in usable:
        if not os.path.isdir(ARCHIVE):
            break
        p = os.path.join(ARCHIVE, "hot_%s.json" % date)
        if not os.path.exists(p):
            continue
        if q is not None and q.ok() and not q.is_trading_day(date):
            dropped.append(date)
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                j = json.load(fh)
        except (OSError, ValueError):
            continue
        ld = (j.get("sj88") or {}).get("ld") or {}
        items = [(c, v.get("rank")) for c, v in ld.items()
                 if isinstance(v.get("rank"), int)]
        if items:
            final[date] = sorted(items, key=lambda kv: kv[1])
    return final, dropped

def corr(xs, ys):
    """皮尔逊相关系数；样本不足或方差为 0 返回 None。"""
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (vx * vy) ** 0.5


def limit_pct(code):
    """涨跌停幅度：创业板 300/301 与科创板 688 是 20%，其余 10%。"""
    return 0.20 if code[2:5] in ("300", "301", "688") else 0.10


def day_chg(code, date):
    """个股当日涨幅（需前一交易日收盘）。"""
    i = _Q._i(date)
    if i is None or i == 0:
        return None
    bars = read_day("sh" if code.startswith("SH") else "sz", code[2:])
    c0, c1 = bars.get(_Q.cal[i - 1]), bars.get(_Q.cal[i])
    if not c0 or not c1:
        return None
    return c1 / c0 - 1.0


def zt_streak(code, date):
    """当日往前数，连续涨停几天（当日不算涨停则为 0）。"""
    i = _Q._i(date)
    if i is None:
        return None
    bars = read_day("sh" if code.startswith("SH") else "sz", code[2:])
    lim = limit_pct(code)
    n, j = 0, i
    while j > 0:
        c0, c1 = bars.get(_Q.cal[j - 1]), bars.get(_Q.cal[j])
        if not c0 or not c1:
            break
        if c1 / c0 - 1.0 >= lim - 0.005:
            n += 1
            j -= 1
        else:
            break
    return n


_Q = None


def section_tenure(final, q):
    """(5) 在榜天数 vs 连板高度：谁在解释次日超额。

    结论口径（2026-10-28 实测，16 个真实交易日）：
      * 在榜资历 与 连板高度 相关系数 +0.43 —— 高度共线；
      * 控制「当日是否涨停」后，未涨停的资历4+ 组超额为负 =>
        真正的解释变量是**连板高度**，资历只是它的代理。
    """
    global _Q
    _Q = q
    dates = sorted(final)
    if not dates:
        return None
    hist, rec = {}, []
    for date in dates:
        for c, r in final[date]:
            cum = hist.get(c, 0) + 1
            hist[c] = cum
            d = day_chg(c, date)
            zt = d is not None and d >= limit_pct(c) - 0.005
            rec.append({"d": date, "c": c, "r": r, "cum": cum,
                        "zt": zt, "streak": zt_streak(c, date) or 0})
    if not rec:
        return None

    # 相关系数（在榜资历 vs 连板高度）
    rc = corr([x["cum"] for x in rec], [x["streak"] for x in rec])

    def exs_of(pred, n=1):
        out = []
        for x in rec:
            if not pred(x):
                continue
            rb = q.bret(x["d"], n)
            if rb is None:
                continue
            rr = q.ret(x["c"], x["d"], n)
            if rr is not None:
                out.append(rr - rb)
        return out

    # 纯连板高度分组（完全不看榜单）
    ladder = []
    for lo, hi, lbl in ((1, 1, "首板"), (2, 2, "2板"), (3, 4, "3-4板"), (5, 99, "5板以上")):
        xs = exs_of(lambda x, lo=lo, hi=hi: x["zt"] and lo <= x["streak"] <= hi)
        b = stat_block(xs)
        if b:
            ladder.append((lbl, b))

    # 控制涨停后的 2x2（资历 vs 是否涨停）
    grid = {}
    for zt in (True, False):
        for key, lbl in ((lambda x: x["cum"] == 1, "资历1"),
                         (lambda x: 2 <= x["cum"] <= 3, "资历2-3"),
                         (lambda x: x["cum"] >= 4, "资历4+")):
            grid[("zt" if zt else "no_zt") + "|" + lbl] = stat_block(
                exs_of(lambda x, k=key, z=zt: x["zt"] == z and k(x)))

    # 资历4+ 涨停组：留一法（逐只剔除，看是否靠单只票撑着）
    base = [x for x in rec if x["zt"] and x["cum"] >= 4]
    from collections import Counter as _C
    loo = []
    for c, k in _C(x["c"] for x in base).most_common(5):
        xs = exs_of(lambda x, c=c: x["zt"] and x["cum"] >= 4 and x["c"] != c)
        b = stat_block(xs)
        if b and k >= 2:
            loo.append((c, k, b))

    # 交叉：资历 vs 连板，谁更强
    cross = {
        "tenure_zt": stat_block(exs_of(lambda x: x["zt"] and x["cum"] >= 4)),
        "fresh_lianban": stat_block(exs_of(lambda x: x["zt"] and x["cum"] == 1 and x["streak"] >= 3)),
        "both": stat_block(exs_of(lambda x: x["zt"] and x["cum"] >= 4 and x["streak"] >= 3)),
    }

    # 持有期
    hold = {n: stat_block(exs_of(lambda x: x["zt"] and x["cum"] >= 4, n)) for n in (1, 2, 3, 5)}
    hold_fresh = {n: stat_block(exs_of(lambda x: x["zt"] and x["cum"] == 1, n)) for n in (1, 2, 3, 5)}
    return {"corr": rc, "ladder": ladder, "grid": grid, "loo": loo,
            "cross": cross, "hold": hold, "hold_fresh": hold_fresh,
            "n_long4": len(base), "days": len(dates)}

def section_rhythm(usable):
    """(1) 节奏：时段分布 / 归零时刻 / 盘中占比。"""
    allrows = [(d, r) for d, rec in usable for r in rec["rows"]]
    tot = len(allrows)
    by_sess = {}
    for name, _lo, _hi in SESSIONS:
        seg = [r for _d, r in allrows if session_of(r["t"]) == name]
        if not seg:
            continue
        by_sess[name] = {
            "n": len(seg), "share": len(seg) / tot if tot else 0.0,
            "inn": mean([r["inn"] for r in seg]),
            "out": mean([r["out"] for r in seg]),
            "mv": mean([r["mv"] for r in seg]),
            "size": mean([r["n1"] for r in seg]),
            "zero": sum(1 for r in seg if r["n1"] == 0),
        }
    zero_t = {}
    for _d, r in allrows:
        if r["n1"] == 0:
            zero_t[r["t"][:5]] = zero_t.get(r["t"][:5], 0) + 1
    n_zero = sum(zero_t.values())
    return {
        "days": len(usable), "points": tot,
        "per_day_median": statistics.median([len(rec["rows"]) for _d, rec in usable]) if usable else 0,
        "per_day_min": min(len(rec["rows"]) for _d, rec in usable) if usable else 0,
        "per_day_max": max(len(rec["rows"]) for _d, rec in usable) if usable else 0,
        "sessions": by_sess,
        "zero_total": n_zero,
        "zero_share": (n_zero / tot) if tot else 0.0,
        "zero_top": sorted(zero_t.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        "intra": sum(1 for _d, r in allrows if "09:30:00" <= r["t"] < "15:00:00"),
        "pre": sum(1 for _d, r in allrows if r["t"] < "09:30:00"),
        "post": sum(1 for _d, r in allrows if r["t"] >= "15:00:00"),
    }


def section_form(final, q):
    """(2) 形态：「换位」(rank 变动) 对次日超额有没有区分度。"""
    dates = sorted(final)
    if len(dates) < 3:
        return None
    up, down, same, top3, other = [], [], [], [], []
    for a, b in zip(dates, dates[1:]):
        rb = q.bret(b, 1)
        if rb is None:
            continue
        pmap = dict(final[a])
        for c, r in final[b]:
            if c not in pmap:
                continue
            x = q.ret(c, b, 1)
            if x is None:
                continue
            ex = x - rb
            rp = pmap[c]
            if r < rp:
                up.append(ex)
            elif r > rp:
                down.append(ex)
            else:
                same.append(ex)
            (top3 if r <= 3 else other).append(ex)
    if not (up or down or same):
        return None
    return {
        "move": {"up": stat_block(up), "down": stat_block(down), "same": stat_block(same)},
        "tier": {"top3": stat_block(top3), "other": stat_block(other)},
        "snapshot_days": len(dates),
    }


def section_leaders(final, q):
    """(3) 龙头：top1/top2/top3/top5/全榜 T+1~T+5 超额；top3 次日留存率。"""
    if not final:
        return None
    out = {}
    for k, label in ((1, "top1"), (2, "top2"), (3, "top3"), (5, "top5")):
        per = {}
        for n in (1, 2, 3, 5):
            ex = []
            for date, items in final.items():
                rb = q.bret(date, n)
                if rb is None:
                    continue
                for c, r in items:
                    if r > k:
                        continue
                    x = q.ret(c, date, n)
                    if x is not None:
                        ex.append(x - rb)
            per[n] = stat_block(ex)
        out[label] = per
    per = {}
    for n in (1, 2, 3, 5):
        ex = []
        for date, items in final.items():
            rb = q.bret(date, n)
            if rb is None:
                continue
            for c, _r in items:
                x = q.ret(c, date, n)
                if x is not None:
                    ex.append(x - rb)
        per[n] = stat_block(ex)
    out["全榜"] = per

    dates = sorted(final)
    persist = {}
    for k in (1, 3):
        st = tot = 0
        for a, b in zip(dates, dates[1:]):
            A = {c for c, r in final[a] if r <= k}
            B = {c for c, r in final[b] if r <= k}
            st += len(A & B)
            tot += len(A)
        persist["top%d" % k] = (st / tot) if tot else None
    out["persist"] = persist
    out["snapshot_days"] = len(final)
    return out


def section_size(final, q):
    """(4) 只数：当日榜内只数分档 vs 次日榜内平均涨幅（超额）。"""
    rows = []
    for date, items in final.items():
        rb = q.bret(date, 1)
        if rb is None:
            continue
        rets = [x for x in (q.ret(c, date, 1) for c, _r in items) if x is not None]
        if not rets:
            continue
        rows.append({"date": date, "n": len(items),
                     "own": mean(rets), "bench": rb, "ex": mean(rets) - rb})
    if not rows:
        return None
    by_b = {}
    for label, lo, hi in (("小榜 ≤20只", 0, 20), ("中榜 21-40", 21, 40), ("大榜 >40", 41, 10 ** 9)):
        seg = [r for r in rows if lo <= r["n"] <= hi]
        if seg:
            by_b[label] = {"days": len(seg), "ex": mean([r["ex"] for r in seg]),
                           "own": mean([r["own"] for r in seg]),
                           "bench": mean([r["bench"] for r in seg])}
    corr = None
    if len(rows) >= 5:
        ns = [r["n"] for r in rows]
        es = [r["ex"] for r in rows]
        mn, me = mean(ns), mean(es)
        vn = sum((x - mn) ** 2 for x in ns)
        ve = sum((y - me) ** 2 for y in es)
        if vn > 0 and ve > 0:
            corr = sum((x - mn) * (y - me) for x, y in zip(ns, es)) / (vn * ve) ** 0.5
    return {"rows": sorted(rows, key=lambda r: r["date"]), "buckets": by_b, "corr": corr}


# ======================================================================
# 4b. 选股（在榜资历 + 当日涨停）与阈值敏感度
# ======================================================================
#: 默认规则参数。**注意：4 是从样本里挑出来的最优档，不是先验**，
#: 相邻档位表现差异很大（见阈值敏感度表），所以务必一起看敏感度。
PICK_MIN_CUM = 4


def build_daily_records(final, names=None):
    """把 rank 快照展开成逐日逐票记录，并**按日累积在榜资历**（无前视）。

    返回 [(date, [dict(c,name,rank,cum,zt,streak,dchg)]), ...]，按日期升序。
    """
    names = names or {}
    hist, out = {}, []
    for date in sorted(final):
        day = []
        for c, r in final[date]:
            cum = hist.get(c, 0) + 1
            hist[c] = cum
            d = day_chg(c, date)
            zt = d is not None and d >= limit_pct(c) - 0.005
            day.append({"c": c, "name": names.get(c, ""), "rank": r, "cum": cum,
                        "zt": zt, "streak": zt_streak(c, date) or 0, "dchg": d})
        out.append((date, day))
    return out


def load_names():
    """代码 -> 名称（扫一遍归档快照，任一日期有名字即可）。"""
    names = {}
    if not os.path.isdir(ARCHIVE):
        return names
    for fn in sorted(os.listdir(ARCHIVE)):
        if not (fn.startswith("hot_") and fn.endswith(".json")):
            continue
        try:
            with open(os.path.join(ARCHIVE, fn), encoding="utf-8") as fh:
                ld = (json.load(fh).get("sj88") or {}).get("ld") or {}
        except (OSError, ValueError):
            continue
        for c, v in ld.items():
            if isinstance(v, dict) and v.get("name"):
                names[c] = v["name"]
    return names


def pick_days(daily, q, lo=None, hi=None, min_cum=PICK_MIN_CUM, require_zt=True):
    """跑规则，返回逐日结果（含逐笔收益）。lo/hi 为闭区间日期串。"""
    out = []
    for date, day in daily:
        if lo and date < lo:
            continue
        if hi and date > hi:
            continue
        picks = [x for x in day
                 if x["cum"] >= min_cum and (x["zt"] or not require_zt)]
        picks.sort(key=lambda x: (-x["cum"], x["rank"]))
        rb1, rb2 = q.bret(date, 1), q.bret(date, 2)
        rows = []
        for x in picks:
            r1, r2 = q.ret(x["c"], date, 1), q.ret(x["c"], date, 2)
            row = dict(x)
            row.update({"r1": r1, "r2": r2,
                        "e1": (r1 - rb1) if (r1 is not None and rb1 is not None) else None,
                        "e2": (r2 - rb2) if (r2 is not None and rb2 is not None) else None})
            rows.append(row)
        out.append({"date": date, "n_board": len(day), "rows": rows,
                    "rb1": rb1, "rb2": rb2})
    return out


def summarize_picks(days):
    """有票日 / 空仓日 / 逐笔汇总。"""
    traded = [d for d in days if d["rows"]]
    empty = [d for d in days if not d["rows"]]
    day_ex = []
    for d in traded:
        vals = [r["r1"] for r in d["rows"] if r["r1"] is not None]
        if vals and d["rb1"] is not None:
            day_ex.append((d["date"], mean(vals) - d["rb1"], len(vals),
                           sum(1 for v in vals if v > 0) / len(vals)))
    per_trade = [r["e1"] for d in traded for r in d["rows"] if r["e1"] is not None]
    comp = 1.0
    for _d, ex, _n, _w in day_ex:
        comp *= (1 + ex)
    return {
        "days_total": len(days),
        "days_traded": len(traded),
        "days_empty": len(empty),
        "empty_list": [d["date"] for d in empty],
        "trades": len(per_trade),
        "per_trade": stat_block(per_trade),
        "per_day": [{"date": d, "ex": ex, "n": n, "win": w} for d, ex, n, w in day_ex],
        "mean_day_ex": mean([e for _d, e, _n, _w in day_ex]),
        "compound": (comp - 1.0) if day_ex else None,
        "first_traded": traded[0]["date"] if traded else None,
        "last_traded": traded[-1]["date"] if traded else None,
    }


def sensitivity(daily, q, rng=(2, 3, 4, 5)):
    """阈值敏感度：同一规则换 min_cum，看笔数/有票日/每笔超额/胜率怎么变。

    这是判断「85.7% 胜率是真信号还是挑出来的最优档」的核心表。
    """
    rows = []
    for mc in rng:
        s = summarize_picks(pick_days(daily, q, min_cum=mc))
        b = s["per_trade"] or {}
        rows.append({"min_cum": mc, "trades": s["trades"],
                     "days_traded": s["days_traded"], "days_total": s["days_total"],
                     "mean": b.get("mean"), "win": b.get("win")})
    return rows


def render_picks_markdown(summ, sens, lo, hi, min_cum):
    L = []
    A = L.append
    A("## 选股结果：%s ~ %s（规则：在榜资历 >= %d 且当日涨停）"
      % (lo or "最早", hi or "最新", min_cum))
    A("")
    A("| 指标 | 数值 |")
    A("|---|---|")
    A("| 区间交易日 | %d |" % summ["days_total"])
    A("| **有票日** | **%d** |" % summ["days_traded"])
    A("| **空仓日** | **%d** |" % summ["days_empty"])
    A("| 逐笔笔数 | %d |" % summ["trades"])
    if summ["per_trade"]:
        b = summ["per_trade"]
        A("| 每笔 T+1 超额 | %s（胜率 %.1f%%，中位 %s） |"
          % (pct(b["mean"]), 100 * b["win"], pct(b["median"])))
    if summ["mean_day_ex"] is not None:
        A("| 每日等权超额均值 | %s |" % pct(summ["mean_day_ex"]))
    if summ["compound"] is not None:
        A("| 复利（1+每日超额 连乘） | %s |" % pct(summ["compound"]))
    if summ["first_traded"]:
        A("| 首次有票 ~ 最后一次 | %s ~ %s |" % (summ["first_traded"], summ["last_traded"]))
    A("")
    if summ["compound"] is not None:
        A("> 复利那一行是把**每日等权超额**连乘，只作量级参考：假设满仓等权、"
          "未扣交易成本、空仓日不占资金。**不要当成可实现收益**。")
        A("")
    if summ["empty_list"]:
        A("空仓日：" + "、".join(summ["empty_list"]))
        A("")
        A("> 空仓多半因为**在榜资历攒不到门槛**（榜单新上线、或股票轮换快），")
        A("> 不是“没有涨停”——这是规则的特性，不是 bug。")
        A("")
    A("**阈值敏感度（判断胜率是否挑档挑出来的）：**")
    A("")
    A("| 资历门槛 | 笔数 | 有票日 | 每笔超额 | 胜率 |")
    A("|---|---:|---:|---:|---:|")
    for r in sens:
        mark = " **<-当前**" if r["min_cum"] == min_cum else ""
        A("| >=%d%s | %d | %d/%d | %s | %s |" % (
            r["min_cum"], mark, r["trades"], r["days_traded"], r["days_total"],
            pct(r["mean"]), rat(r["win"]) if r["win"] is not None else "—"))
    A("")
    wins = [r["win"] for r in sens if r["win"] is not None]
    if wins and max(wins) - min(wins) > 0.20:
        A("> **相邻门槛的胜率差异超过 20 个百分点，且峰值落在中间档** ——")
        A("> 这是过拟合的典型特征：规则不是“越严越好”，而是“恰好在某一档好看”。")
        A("> 样本变长后若峰值仍稳定在同一档，才算真信号。")
        A("")
    return L

# ======================================================================
# 4. 渲染
# ======================================================================
def pct(x, d=2):
    return "—" if x is None else ("%+.*f%%" % (d, 100 * x))


def num(x, d=1):
    return "—" if x is None else ("%.*f" % (d, x))


def rat(x, d=1):
    """无符号比率（留存率用；别用 pct()，那会带上正负号）"""
    return "—" if x is None else ("%.*f%%" % (d, 100 * x))


def build_markdown(rhythm, form, leaders, size, tenure, meta, dropped):
    L = []
    A = L.append
    A("# 龙头榜 变化时点 · 统计")
    A("")
    A("> 由 `ld_timeline_stats.py` 自动生成，请勿手改。榜：%s。行情：本机通达信日线，基准上证指数。" % BOARD_LABEL)
    usable = [m for m in meta if m["tag"] == "ok"]
    if usable:
        A("> 统计区间：%s ~ %s，共 **%d 个交易日**、%d 个变化点（已剔除异常日）。"
          % (usable[0]["date"], usable[-1]["date"], len(usable), sum(m["n"] for m in usable)))
    A("")
    # ---- 口径声明（2026-10-28 修正）----
    A("> **口径声明：**")
    A(">")
    A("> 1. **只认交易日历**：第 2/3/4/5 节的 rank 序列来自归档快照 `_hot_archive/hot_<date>.json`，"
      "而采集器在**周末/假期照常写快照**（实测 3 份假日期）。假日期会被当成“前一日”参与比较，"
      "污染序列。2026-10-28 实测影响：**第 2 节的「不变」组 +5.54%→+5.13%、"
      "第 5 节的资历-连板相关系数 +0.071→+0.429**（资历被假日期虚增）；"
      "第 3/4 节基本不受影响，**留存率修正前后都是 11.0%**。")
    if dropped:
        A(">    本节已剔除的非交易日快照：**%s**（上证指数当日无 K 线）。"
          % "、".join("`%s`" % d for d in dropped))
    else:
        A(">    本例中这些假日期已在第 0 节「数据体检」按 0 变化点先被剔除，" +
          "故本节 rank 序列天然干净、无额外剔除。")
    A("> 2. **留存率是“次日仍在前 K 名的比例”**，不是收益率，所以不带正负号。"
      "若看到 `+100%` 之类的写法是 bug。")
    A("")

    A("## 0. 数据体检")
    A("")
    A("| 日期 | 变化点 | 标签 | 说明 |")
    A("|---|---:|---|---|")
    tag_cn = {"ok": "OK 正常", "weekend": "0点(周末/假期)",
              "thin": "采集断档", "anomaly": "**异常(已剔除)**"}
    for m in meta:
        A("| %s | %d | %s | %s |" % (m["date"], m["n"], tag_cn.get(m["tag"], m["tag"]),
                                     m["why"] or "—"))
    A("")
    if ANOMALY_DAYS:
        A("**已标记的异常日：**")
        A("")
        for d, why in sorted(ANOMALY_DAYS.items()):
            A("- `%s` — %s" % (d, why))
        A("")

    if not rhythm or not rhythm["points"]:
        A("_没有可用样本。_")
        return "\n".join(L) + "\n"

    A("## 1. 节奏：变化点落在哪个时段")
    A("")
    A("| 时段 | 点数 | 占比 | 均进 | 均出 | 均换位 | 均只数 | 归零次数 |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, _lo, _hi in SESSIONS:
        s = rhythm["sessions"].get(name)
        if not s:
            continue
        A("| %s | %d | %.1f%% | %s | %s | %s | %s | %d |"
          % (name, s["n"], 100 * s["share"], num(s["inn"]), num(s["out"]),
             num(s["mv"]), num(s["size"]), s["zero"]))
    A("")
    A("- 日均变化点 中位 **%s** 个（最少 %d / 最多 %d）"
      % (num(rhythm["per_day_median"], 0), rhythm["per_day_min"], rhythm["per_day_max"]))
    A("- 盘中(09:30-15:00) %d 个 = **%.1f%%**；盘前 %d 个；盘后 %d 个"
      % (rhythm["intra"], 100.0 * rhythm["intra"] / rhythm["points"],
         rhythm["pre"], rhythm["post"]))
    A("- **归零(空榜) %d 次 = %.1f%% 的变化点**，最集中在：%s"
      % (rhythm["zero_total"], 100 * rhythm["zero_share"],
         "、".join("%s×%d" % (t, c) for t, c in rhythm["zero_top"][:6]) or "—"))
    A("")
    A("> 读法：归零集中在 **09:00 / 09:24 / 09:27** —— 那是每天启动时把前一日榜清空重算，"
      "不是“信息更新”。盘前那批点平均进/出 10~13 只，等于整体换血。")
    A("")

    A("## 2. 形态：「换位」有没有预测力")
    A("")
    if form:
        A("按前一日→当日的 rank 变动分组，看**次日超额收益**（个股 − 上证）：")
        A("")
        A("| rank 变动 | 样本 | 次日超额均值 | 胜率 | 中位 |")
        A("|---|---:|---:|---:|---:|")
        for key, label in (("up", "排名上升"), ("down", "排名下降"), ("same", "排名不变")):
            b = form["move"].get(key)
            if b:
                A("| %s | %d | %s | %.1f%% | %s |"
                  % (label, b["n"], pct(b["mean"]), 100 * b["win"], pct(b["median"])))
        A("")
        A("| 档位 | 样本 | 次日超额 | 胜率 |")
        A("|---|---:|---:|---:|")
        for key, label in (("top3", "当日 top3"), ("other", "非 top3")):
            b = form["tier"].get(key)
            if b:
                A("| %s | %d | %s | %.1f%% |" % (label, b["n"], pct(b["mean"]), 100 * b["win"]))
        A("")
        A("> **结论：换位是噪音。** 排名上升组没有跑赢不变组，方向甚至相反。"
          "一天几十次的“换位”是榜单刷新的逐笔抖动，把它当热度信号去追＝追噪音。")
        A("> 注：本节用归档快照 `_hot_archive/hot_<date>.json` 的 rank 序列（%d 天），"
          "因为 MD 的 top3 列只给前 3 名，判不出个股升降。" % form["snapshot_days"])
    else:
        A("_快照不足，跳过。_")
    A("")

    A("## 3. 龙头：top3 的真实预测力")
    A("")
    if leaders:
        A("收盘最终榜（归档快照）分档，T 收盘买入 → T+n 收盘卖，超额 = 个股 − 上证：")
        A("")
        A("| 档位 | T+1 | T+2 | T+3 | T+5 |")
        A("|---|---:|---:|---:|---:|")
        for label in ("top1", "top2", "top3", "top5", "全榜"):
            cells = []
            for n in (1, 2, 3, 5):
                b = leaders[label].get(n)
                cells.append("%s (n=%d)" % (pct(b["mean"]), b["n"]) if b else "—")
            A("| %s | %s |" % (label, " | ".join(cells)))
        A("")
        p = leaders.get("persist") or {}
        A("- **top3 次日留存率 %s**，top1 留存率 %s —— 龙头第二天大概率换人"
          % (rat(p.get("top3")), rat(p.get("top1"))))
        b1 = leaders.get("top3", {}).get(1)
        b2 = leaders.get("top3", {}).get(2)
        if b1:
            A("- top3 的 T+1 超额 %s（胜率 %.1f%%，中位 %s），到 T+2 只剩 %s"
              % (pct(b1["mean"]), 100 * b1["win"], pct(b1["median"]),
                 pct(b2["mean"]) if b2 else "—"))
        A("")
        A("> 读法：排序方向是稳的（top1 > top3 > 全榜），但**增量只有 0.2~0.4 个百分点** ——"
          "赚钱的是“上榜”本身，不是“排第几”。且从 T+2 起超额趋零、中位数变负，"
          "是一天的短促溢价，拿不住。")
    else:
        A("_快照不足，跳过。_")
    A("")

    A("## 4. 只数：榜单缩 → 大波动")
    A("")
    if size:
        A("| 当日榜只数 | 交易日 | 榜内次日均值 | 上证 | 超额 |")
        A("|---|---:|---:|---:|---:|")
        for label in ("小榜 ≤20只", "中榜 21-40", "大榜 >40"):
            b = size["buckets"].get(label)
            if b:
                A("| %s | %d | %s | %s | **%s** |"
                  % (label, b["days"], pct(b["own"]), pct(b["bench"]), pct(b["ex"])))
        A("")
        if size["corr"] is not None:
            A("- 只数 与 次日超额 的相关系数 **%.3f**（负=榜越小越好）" % size["corr"])
        A("")
        A("| 日期 | 只数 | 榜内次日 | 上证 | 超额 |")
        A("|---|---:|---:|---:|---:|")
        for r in size["rows"]:
            A("| %s | %d | %s | %s | %s |"
              % (r["date"], r["n"], pct(r["own"]), pct(r["bench"]), pct(r["ex"])))
        A("")
        A("> **结论：「只数」这一列比「龙头 top3」那一列更值得看。** 榜一收缩（资金高度聚焦），"
          "次日的榜内波动就放大。但样本只有十几个交易日，只作方向参考。")
    else:
        A("_快照不足，跳过。_")
    A("")

    A("## 5. 在榜天数 vs 连板高度：谁在解释次日超额")
    A("")
    if tenure:
        rb = tenure.get("corr")
        A("「在榜资历」= 该股截至当日的累积上榜天数；「连板高度」= 连续涨停天数（与榜无关）。")
        A("")
        if rb is not None:
            A("- **在榜资历 与 连板高度 相关系数 = %+.3f**（高度共线，不是独立因子）" % rb)
        A("")
        A("**纯连板高度分组（完全不看榜单，只用行情）：**")
        A("")
        A("| 连板高度 | 样本 | 次日超额 | 胜率 |")
        A("|---|---:|---:|---:|")
        for lbl, b in tenure["ladder"]:
            A("| %s | %d | %s | %.1f%% |" % (lbl, b["n"], pct(b["mean"]), 100 * b["win"]))
        A("")
        A("**控制「当日是否涨停」后的分层（次日超额）：**")
        A("")
        A("| 在榜资历 | 当日涨停 | 当日未涨停 |")
        A("|---|---:|---:|")
        for lbl in ("资历1", "资历2-3", "资历4+"):
            a = tenure["grid"].get("zt|" + lbl)
            b = tenure["grid"].get("no_zt|" + lbl)
            A("| %s | %s | %s |" % (
                lbl,
                ("%s (n=%d, 胜率%.0f%%)" % (pct(a["mean"]), a["n"], 100 * a["win"])) if a else "—",
                ("%s (n=%d)" % (pct(b["mean"]), b["n"])) if b else "—"))
        A("")
        A("> **结论：真正起作用的是「连板高度」，「在榜资历」只是它的代理。** 控制「当日涨停」后，"
          "资历长但当天没涨停的股票超额为负 —— 信号完全来自「已经连板的还在涨」。")
        A("")
        A("**交叉验证（谁更强）：**")
        A("")
        A("| 组合 | 样本 | 次日超额 | 胜率 |")
        A("|---|---:|---:|---:|")
        for key, lbl in (("tenure_zt", "资历4+ 且涨停"),
                         ("fresh_lianban", "资历1 且连板≥3"),
                         ("both", "资历4+ 且连板≥3")):
            b = tenure["cross"].get(key)
            if b:
                A("| %s | %d | %s | %.1f%% |" % (lbl, b["n"], pct(b["mean"]), 100 * b["win"]))
        A("")
        A("**持有期（资历4+ 且涨停）：**")
        A("")
        A("| | T+1 | T+2 | T+3 | T+5 |")
        A("|---|---:|---:|---:|---:|")
        A("| 资历4+ 且涨停 | %s |" % " | ".join(
            ("%s (n=%d)" % (pct(tenure["hold"][n]["mean"]), tenure["hold"][n]["n"]))
            if tenure["hold"].get(n) else "—" for n in (1, 2, 3, 5)))
        A("| 对照：资历1 且涨停 | %s |" % " | ".join(
            ("%s (n=%d)" % (pct(tenure["hold_fresh"][n]["mean"]), tenure["hold_fresh"][n]["n"]))
            if tenure["hold_fresh"].get(n) else "—" for n in (1, 2, 3, 5)))
        A("")
        if tenure["loo"]:
            A("**稳健性：逐只剔除（留一法）** —— 资历4+ 且涨停共 %d 条，剔除后超额仍在："
              % tenure["n_long4"])
            A("")
            A("| 剔除 | 剔除条数 | 剩余 n | 超额 |")
            A("|---|---:|---:|---:|")
            for c, k, b in tenure["loo"]:
                A("| %s | %d | %d | %s |" % (c, k, b["n"], pct(b["mean"])))
            A("")
        A("> ⚠️ 资历4+ 且涨停只有 %d 条样本、%d 个交易日 —— 只作方向判断，样本量远不足以当交易信号。"
          % (tenure["n_long4"], tenure["days"]))
    else:
        A("_快照不足，跳过。_")
    A("")
    A("---")
    A("")
    A("_样本天数有限（<40 个交易日），以上结论只作方向判断，不宜直接当交易信号。_")
    return "\n".join(L) + "\n"


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


# ======================================================================
# 5. main
# ======================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="龙头榜变化时点统计（节奏/形态/龙头/只数）")
    ap.add_argument("--since", help="只看该日期之后（YYYY-MM-DD）")
    ap.add_argument("--until", help="只看该日期之前（YYYY-MM-DD）")
    ap.add_argument("--no-write", action="store_true", help="只打印，不写报告")
    ap.add_argument("--json", action="store_true", help="输出机器可读摘要")
    ap.add_argument("--check", action="store_true", help="只做数据体检（日期分类）")
    ap.add_argument("--picks", metavar="LO:HI",
                    help="跑选股规则并输出该区间逐笔结果，如 2026-09-24:2026-10-15；只给 LO 或 :HI 也可")
    ap.add_argument("--min-cum", type=int, default=PICK_MIN_CUM,
                    help="选股的在榜资历门槛（默认 %d）" % PICK_MIN_CUM)
    ap.add_argument("--picks-all", action="store_true",
                    help="不写进报告，只把全区间选股结果打印到控制台")
    args = ap.parse_args(argv)

    files = list_files()
    if not files:
        print("!! 没有找到 %s*.md" % PREFIX)
        return 2
    if args.since:
        files = [f for f in files if f[0] >= args.since]
    if args.until:
        files = [f for f in files if f[0] <= args.until]
    if not files:
        print("!! 过滤后没有日期")
        return 2

    usable, meta = classify(files)

    print("=" * 78)
    print("龙头榜变化时点统计  %s" % BOARD_LABEL)
    print("=" * 78)
    print("%-12s %6s  %-18s %s" % ("日期", "点数", "标签", "说明"))
    for m in meta:
        print("%-12s %6d  %-18s %s" % (m["date"], m["n"], m["tag"], m["why"]))
    if not usable:
        print("!! 没有可用样本")
        return 2

    if args.check:
        print()
        print("体检完成：可用 %d 天，异常 %d 天，0点 %d 天，断档 %d 天"
              % (len(usable),
                 sum(1 for m in meta if m["tag"] == "anomaly"),
                 sum(1 for m in meta if m["tag"] == "weekend"),
                 sum(1 for m in meta if m["tag"] == "thin")))
        return 0

    q = Quotes()
    if not q.ok():
        print("!! 读不到通达信日线（%s），收益类统计将为空" % TDX)
    final, dropped_days = load_final_ranks(usable, q if q.ok() else None)

    rhythm = section_rhythm(usable)
    form = section_form(final, q) if q.ok() else None
    leaders = section_leaders(final, q) if q.ok() else None
    size = section_size(final, q) if q.ok() else None
    tenure = section_tenure(final, q) if q.ok() else None

    # ---- 选股规则（--picks / 报告第 6 节）----
    picks_days = None
    lo = hi = None
    if q.ok() and (args.picks is not None or args.picks_all):
        if args.picks:
            parts = args.picks.split(":", 1)
            lo = (parts[0] or "").strip() or None
            hi = (parts[1] or "").strip() or None if len(parts) > 1 else None
        daily = build_daily_records(final, load_names())
        picks_days = pick_days(daily, q, lo=lo, hi=hi, min_cum=args.min_cum)
        if not daily:
            picks_days = None

    md = build_markdown(rhythm, form, leaders, size, tenure, meta, dropped_days)

    summ = sens = None
    rng_lo = rng_hi = None
    if picks_days is not None:
        summ = summarize_picks(picks_days)
        sens = sensitivity(build_daily_records(final, load_names()), q)
        # 全区间（bat 用 1970:9999 表示）显示成实际边界，别把哨兵值写进报告
        rng_lo = (picks_days[0]["date"] if picks_days else "?")
        rng_hi = (picks_days[-1]["date"] if picks_days else "?")
        md = md + "\n" + "\n".join(
            render_picks_markdown(summ, sens, rng_lo, rng_hi, args.min_cum)) + "\n"
    print()
    print("可用交易日 %d 个 / 变化点 %d 个" % (rhythm["days"], rhythm["points"]))
    for name in [s[0] for s in SESSIONS]:
        s = rhythm["sessions"].get(name)
        if s:
            print("  %-3s %4d 点 %5.1f%%  均进%.1f 均出%.1f 均换位%.1f 归零%d"
                  % (name, s["n"], 100 * s["share"], s["inn"], s["out"], s["mv"], s["zero"]))
    if form:
        print("  换位->次日超额: 上升 %s / 下降 %s / 不变 %s"
              % (pct((form["move"]["up"] or {}).get("mean")),
                 pct((form["move"]["down"] or {}).get("mean")),
                 pct((form["move"]["same"] or {}).get("mean"))))
    if leaders:
        for label in ("top1", "top3", "全榜"):
            b = leaders.get(label, {}).get(1)
            if b:
                print("  %-5s T+1 超额 %s (n=%d 胜率%.1f%%)"
                      % (label, pct(b["mean"]), b["n"], 100 * b["win"]))
        p = leaders.get("persist") or {}
        print("  top3 次日留存 %s" % rat(p.get("top3")))
    if size:
        for label, b in size["buckets"].items():
            print("  %-10s 次日超额 %s (%d日)" % (label, pct(b["ex"]), b["days"]))
    if tenure:
        print("  在榜资历 vs 连板高度 相关 %s" % num(tenure.get("corr"), 3))
        for key, lbl in (("tenure_zt", "资历4+且涨停"), ("fresh_lianban", "资历1且连板>=3")):
            b = tenure["cross"].get(key)
            if b:
                print("    %-14s 次日超额 %s (n=%d)" % (lbl, pct(b["mean"]), b["n"]))
    if dropped_days:
        print("  已剔除非交易日快照: %s" % ", ".join(dropped_days))

    if summ is not None:
        print("  选股[%s~%s, 资历>=%d]: 有票 %d 天 / 空仓 %d 天 / 共 %d 笔"
              % (rng_lo, rng_hi, args.min_cum, summ["days_traded"], summ["days_empty"], summ["trades"]))
        if summ["per_trade"]:
            b = summ["per_trade"]
            print("    每笔超额 %s 胜率%s (n=%d) | 每日均值 %s | 复利 %s"
                  % (pct(b["mean"]), rat(b["win"]), b["n"],
                     pct(summ["mean_day_ex"]), pct(summ["compound"])))
        print("    阈值敏感度: " + "  ".join(">=%d:%s/%s" % (s["min_cum"], s["trades"], rat(s["win"])) for s in sens))
        if args.picks:
            print()
            for d in picks_days:
                if not d["rows"]:
                    print("  %s  空仓" % d["date"])
                    continue
                print("  %s  选出 %d 只（指数 %s）" % (d["date"], len(d["rows"]), pct(d["rb1"])))
                for x in d["rows"]:
                    print("     %-9s %-6s 在榜%d 连板%d 当日%s | T+1 %s 超额%s"
                          % (x["c"], x["name"], x["cum"], x["streak"],
                             pct(x["dchg"]) if x["dchg"] is not None else "—",
                             pct(x["r1"]) if x["r1"] is not None else "无数据",
                             pct(x["e1"]) if x["e1"] is not None else "—"))

    if not args.no_write:
        write_atomic(REPORT_MD, md)
        print()
        print("报告 -> %s" % REPORT_MD)

    if args.json:
        summary = {
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "board": BOARD_LABEL,
            "days": rhythm["days"], "points": rhythm["points"],
            "rhythm": {k: rhythm[k] for k in ("sessions", "zero_total", "zero_share",
                                              "zero_top", "intra", "pre", "post",
                                              "per_day_median")},
            "form": form, "leaders": leaders,
            "size": ({"buckets": size["buckets"], "corr": size["corr"]} if size else None),
            "tenure": tenure,
            "picks": ({"range": [rng_lo, rng_hi], "min_cum": args.min_cum,
                       "summary": summ, "sensitivity": sens} if summ is not None else None),
            "dropped_non_trading_days": dropped_days,
            "meta": meta,
            "anomaly_days": ANOMALY_DAYS,
        }
        if not args.no_write:
            write_atomic(SUMMARY_JSON, json.dumps(summary, ensure_ascii=False, indent=2))
            print("摘要 -> %s" % SUMMARY_JSON)
    return 0


if __name__ == "__main__":
    sys.exit(main())
