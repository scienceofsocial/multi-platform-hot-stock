# -*- coding: utf-8 -*-
"""五平台人气共振 -> 每日 Markdown 日报落盘。

数据来源（都在本脚本所在目录）
------------------------------
* ``last_good.json``       a_fetch_hot_snapshot.py 抓的五平台人气榜前 20 快照（主数据；
                            同花顺 / 财联社 / 通达信仅留档）
                            + 百度财经热搜「A股 · 今日」前 10（``baidu`` 字段，反向项、仅展示）
* ``hot_seen.json``        当日「已出现股票」首现时间（统计「当日累计上榜」）
* ``jygs_red_cache.json``  韭研公社异动图红股缓存（登记识别口径日 / 抓图时刻）

输出
----
``五平台人气共振_日报_YYYY-MM-DD.md``（每轮整份覆盖写，只留当日终态）
``_hot_archive/report_trace.jsonl``（追加、永不覆盖：抹平「快照抓取时刻 / 时效状态」后
榜单内容真变了才追加一行，用来留「人气何时变、怎么变」的历史轨迹）

打分口径
--------
与 a_export_tdx_hot_rank.py / a_duopingtai_hot_factor.py 一字不差（直接 import 复用
``COVER_WEIGHT`` / ``score_all`` / ``collect_best_ranks``），日报只负责展示：

    共振分     = 加权覆盖平台数 x 1000 + Σ_榜单 max(0, 21 - 该榜单名次) x 平台名次分权重 + 韭研红股 120
    覆盖平台数 = 上榜平台的**加权**去重数（**55188 记 2.0**，
                 其余记 1.0，故理论满配 = 6.0、为整数；开盘啦复盘、55188 主力/人气/龙头各榜得分
                 相加、但仍只算 1 个平台；韭研公社异动图红股无名次、算 1 个平台、另固定给 120 分）

名次分权重：**55188 主力 / 人气 / 龙头 三榜各 x3**（单榜上限 20 -> 60，三榜合计 180），
东方财富 / 淘股吧 / 开盘啦三家口径完全一致（均 x1）；
6 张计分榜加权后上限 240，加韭研红股 120 = 360。同花顺 / 财联社 / 通达信已**彻底剔除**
（不计加权覆盖平台数、不产生名次分，快照 ``ths_poi`` / ``cls`` / ``tdx`` 仅留档）。

百度财经热搜是**反向项**（数据说明 §9）：日报只如实展示命中只数（``baidu`` 条数），不参与上面
这份共振分 —— 该减项只落在 a_duopingtai_hot_factor.py 的因子面板，日报不为它另写打分逻辑。

用法
----
    python a_report_daily.py                    # 读 last_good.json 出当日日报
    python a_report_daily.py --date 2026-09-23  # 覆盖口径日
    python a_report_daily.py --top 20           # 共振榜展示条数（默认 15）
    python a_report_daily.py --out x.md         # 指定输出文件
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 唯一口径来源：五平台榜单定义 + 打分实现
import a_duopingtai_hot_factor as hot                                        # noqa: E402
import a_export_tdx_hot_rank as tx                                           # noqa: E402
import a_fetch_hot_snapshot as fetcher                                       # noqa: E402
import hot_trace as trace                                                    # noqa: E402

#: 日报「变化轨迹」JSONL（追加、永不覆盖）；与快照/明细两份 trace 同放 _hot_archive
TRACE_NAME = "report_trace.jsonl"
TRACE_PATH = os.path.join(trace.TRACE_DIR, TRACE_NAME)

SNAP_NAME = "last_good.json"
JYGS_CACHE_NAME = "jygs_red_cache.json"

#: 明细表里的榜单展示顺序（短标签 -> collect_best_ranks 的榜单键；只列计分榜）
BOARD_ORDER = (("em", "东方财富"), ("tgb", "淘股吧"),
               ("fp", "开盘啦·复盘"),
               ("sj88zl", "55188·主力"), ("sj88rb", "55188·人气"),
               ("sj88ld", "55188·龙头"))


def load_json(path, default=None):
    """读 JSON；不存在或损坏返回 default（日报不该因旁路文件缺失而失败）。"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def board_ranks(rec):
    """某只股票的名次明细 -> ``em7 tgb1 ths6 ...``（缺席的榜单不显示）。"""
    parts = []
    for label, board in BOARD_ORDER:
        rank = rec.get(board)
        if rank is not None:
            parts.append("%s%d" % (label, rank))
    return " ".join(parts) if parts else "-"


def platform_rows(snap):
    """快照 -> [(平台, 榜单, 条数)]，如实反映本轮抓到的原始条数。"""
    tgb = snap.get("tgb") or {}
    kph = snap.get("kph") or {}
    sj88 = snap.get("sj88") or {}
    return [
        ("东方财富", "人气榜", len(snap.get("em") or {})),
        ("淘股吧", "实时热搜", len(tgb.get("rt") or {})),
        ("淘股吧", "24h热搜", len(tgb.get("h24") or {})),
        ("开盘啦", "复盘人气榜", len(kph.get("fp") or {})),
        ("55188", "主力排名", len(sj88.get("zl") or {})),
        ("55188", "人气热榜", len(sj88.get("rb") or {})),
        ("55188", "龙头（龙一~龙十）", len(sj88.get("ld") or {})),
        ("韭研公社", "异动图红股", len(snap.get("jygs") or {})),
        ("百度热搜", "A股·今日前10（反向）", len(snap.get("baidu") or {})),
    ]


def build_report(snap, date, stamp, top, seen, jygs_meta):
    """拼日报 Markdown 文本。"""
    items = tx.score_all(snap)
    by_code = {it["code"]: it for it in items}
    best = hot.collect_best_ranks(snap)
    inst_by_code = {inst.partition(".")[0]: inst for inst in best}

    fetched, mins = tx.freshness(snap)
    if mins is None:
        status = "未知（快照内 fetched_at 缺失）"
    elif mins > 30:
        status = "**已停更 %.0f 分钟**（指标不会变化，请检查 a_fetch_hot_snapshot.py）" % mins
    else:
        status = "新鲜（%.0f 分钟前抓取）" % mins

    # cover 是**加权**平台数（55188 记 2.0），取其实际值统计（0 ~ 6.0 的整数档）
    dist = {}
    for it in items:
        dist[it["cover"]] = dist.get(it["cover"], 0) + 1
    resonance = sum(1 for it in items if it["cover"] >= 2)
    baidu = snap.get("baidu") or {}

    L = []
    L.append("# 五平台人气共振 · 日报")
    L.append("")
    L.append("> 口径日 **%s**（数据戳 %d） · 数据来源 last_good.json（东方财富 / 淘股吧 / 开盘啦(复盘) /"
             " 55188 / 韭研公社 各榜前 20）"
             % (date, stamp))
    L.append("")
    L.append("## 一、运行摘要")
    L.append("")
    L.append("| 项目 | 值 |")
    L.append("| --- | --- |")
    L.append("| 口径日 | %s |" % date)
    L.append("| 快照抓取时刻 | %s |" % fetched)
    L.append("| 时效状态 | %s |" % status)
    L.append("| 覆盖个股 | %d 只（加权覆盖 ≥2 的 %d 只 · 其余 %d 只）"
             % (len(items), resonance, len(items) - resonance))
    L.append("| 百度热搜命中 | %d 只（A股·今日前 10，**反向项**：命中者因子 cover_platforms 减 1，"
             "只影响因子面板、不参与上方共振分） |" % len(baidu))
    L.append("| 共振分区间 | %.0f ~ %.0f |" % (items[-1]["score"], items[0]["score"]))
    full5 = [it for it in items if it["cover"] >= 6.0]
    L.append("| 五平台共振 | %d 只%s |"
             % (len(full5),
                "（%s）" % "、".join(it["name"] or it["code"] for it in full5) if full5 else ""))
    if seen and seen.get("date") == date:
        L.append("| 当日累计上榜 | %d 只（首现时间记于 %s）|"
                 % (len(seen.get("first_seen") or {}), fetcher.SEEN_NAME))
    else:
        L.append("| 当日累计上榜 | 无当日状态（%s 口径日不匹配） |" % fetcher.SEEN_NAME)
    L.append("")
    L.append("打分口径：`共振分 = 加权覆盖平台数 x 1000 + Σ_榜单 max(0, 21 - 该榜单名次) "
             "x 平台名次分权重 + 韭研红股 120`；"
             "加权覆盖平台数按平台去重求和（**55188 记 2.0**，其余记 1.0，"
             "理论满配 6.0；开盘啦复盘、55188 主力/人气/龙头各榜得分相加、"
             "但仍只算 1 个平台）；"
             "名次分权重**55188 主力 / 人气 / 龙头 三榜各 x3**（单榜上限 60，三榜合计 180）、"
             "东方财富 / 淘股吧 / 开盘啦三家口径完全一致（均 x1）；"
             "韭研公社异动图红股无名次，算 1 个平台、另固定给 120 分。")
    L.append("")

    L.append("## 二、各平台抓取条数（本轮原始）")
    L.append("")
    L.append("| 平台 | 榜单 | 条数 |")
    L.append("| --- | --- | ---: |")
    for plat, board, n in platform_rows(snap):
        L.append("| %s | %s | %d |" % (plat, board, n))
    L.append("")

    L.append("## 三、覆盖与档位分布")
    L.append("")
    L.append("> 覆盖平台数为**加权**值（55188 记 2.0，其余各记 1.0），理论取值 0 ~ 6.0 的整数档。")
    L.append("")
    L.append("| 覆盖平台数 | 只数 |")
    L.append("| ---: | ---: |")
    for n in range(6, -1, -1):
        L.append("| %.1f 平台 | %d |" % (float(n), dist.get(n, 0)))
    L.append("| **合计** | **%d** |" % len(items))
    L.append("")

    L.append("## 四、共振榜 Top %d" % top)
    L.append("")
    L.append("| # | 代码 | 名称 | 覆盖平台 | 共振分 | 名次分 | 韭研红股 | 各榜名次 |")
    L.append("| ---: | --- | --- | ---: | ---: | ---: | :---: | --- |")
    for i, it in enumerate(items[:top], 1):
        rec = best.get(inst_by_code.get(it["code"], ""), {})
        L.append("| %d | %s | %s | %.1f | %.0f | %.0f | %s | %s |"
                 % (i, it["code"], it["name"] or "-", it["cover"], it["score"],
                    it["rank_score"],
                    "Y" if rec.get(hot.JYGS_BOARD) is not None else "",
                    board_ranks(rec)))
    L.append("")

    jygs = snap.get("jygs") or {}
    added, alone = [], []
    for code, name in jygs.items():
        bare = hot.to_instrument(code).partition(".")[0]     # SH603636 -> 603636
        it = by_code.get(bare)
        if it is None:
            continue
        (added if it["cover"] >= 2 else alone).append((bare, name or it["name"], it))
    added.sort(key=lambda t: (-t[2]["score"], t[0]))
    alone.sort(key=lambda t: t[0])

    L.append("## 五、韭研公社异动图红股明细（%d 只）" % len(jygs))
    L.append("")
    if jygs_meta:
        L.append("> 缓存抓取于 %s，异动图对应口径日 %s，图源 %s。"
                 % (jygs_meta.get("fetched_at") or "未知",
                    jygs_meta.get("source_date") or "未知",
                    jygs_meta.get("diagram") or "未知"))
        L.append("")
    L.append("### 5.1 靠韭研新增覆盖的 %d 只（原本已在其他平台上榜）" % len(added))
    L.append("")
    L.append("| 代码 | 名称 | 覆盖平台 | 共振分 | 各榜名次 |")
    L.append("| --- | --- | ---: | ---: | --- |")
    for code, name, it in added:
        rec = best.get(inst_by_code.get(code, ""), {})
        L.append("| %s | %s | %.1f | %.0f | %s |"
                 % (code, name or it["name"] or "-", it["cover"], it["score"], board_ranks(rec)))
    if not added:
        L.append("| - | - | - | - | - |")
    L.append("")
    L.append("### 5.2 仅韭研单平台的 %d 只（共振分 1120 = 1 平台 x 1000 + 韭研红股固定 120，仅覆盖计数）"
             % len(alone))
    L.append("")
    L.append("| 代码 | 名称 |")
    L.append("| --- | --- |")
    for code, name, _ in alone:
        L.append("| %s | %s |" % (code, name or "-"))
    if not alone:
        L.append("| - | - |")
    L.append("")

    L.append("## 六、输出产物")
    L.append("")
    L.append("| 文件 | 说明 |")
    L.append("| --- | --- |")
    L.append("| `last_good.json` | 五平台榜单快照（本日报的唯一数据源） |")
    L.append("| `hot_seen.json` | 当日首现时间（跨日自动清空） |")
    L.append("| `jygs_red_cache.json` | 韭研公社异动图红股缓存（当日复用） |")
    L.append("| `五平台人气共振_通达信排序指标.txt` | 通达信排序公式源码（RENQI8） |")
    L.append("| `%s\\<市场>_<代码>.dat` | %d 只个股的共振分（通达信 .901 数据号 %d）"
             % (tx.SIG_DIR, len(items), tx.SIG_NO))
    L.append("| `五平台人气共振_日报_%s.md` | 本文件（每轮覆盖写） |" % date)
    L.append("| `_hot_archive\\hot_trace.jsonl` | 快照变化轨迹（榜单内容变化才追加一行） |")
    L.append("| `_hot_archive\\factor_trace.jsonl` | 明细表变化轨迹（a_duopingtai_hot_factor.py 产出） |")
    L.append("| `_hot_archive\\report_trace.jsonl` | 本日报变化轨迹（追加、永不覆盖） |")
    L.append("")

    L.append("## 七、异常 / 备注")
    L.append("")
    notes = []
    if mins is not None and mins > 30:
        notes.append("快照已停更 %.0f 分钟：本轮分值沿用上一轮，需检查抓取链路。" % mins)
    if jygs_meta and jygs_meta.get("source_date") and str(jygs_meta["source_date"]) != date:
        notes.append("韭研公社异动图对应口径日 %s（缓存抓于 %s），与榜单口径日 %s 可能相差一个"
                     "交易日，属正常（红股取材自盘后异动图）。"
                     % (jygs_meta["source_date"], jygs_meta.get("fetched_at") or "未知", date))
    empty = [plat for plat, _, n in platform_rows(snap) if n == 0 and plat != "百度热搜"]
    if empty:
        notes.append("本轮条数为 0 的榜单：" + "、".join(empty) + "（抓取失败时沿用上一轮数据）。")
    if not baidu:
        notes.append("当日百度热搜未抓到（失败时**不沿用旧快照**、按空榜处理）：命中只数记 0，"
                     "本日因子没有百度反向扣分，其余五平台口径不受影响。")
    for n in notes:
        L.append("- %s" % n)
    L.append("")
    return L, items, dist, resonance, len(jygs)


#: 日报里「每轮必变」的行（抓取时刻 / 时效分钟数）——不抹平就会每轮都判定为「有变化」
VOLATILE_LINES = (
    re.compile(r"^\| 快照抓取时刻 \|.*\|\s*$", re.MULTILINE),
    re.compile(r"^\| 时效状态 \|.*\|\s*$", re.MULTILINE),
)


def report_fingerprint(text):
    """日报全文 -> 榜单指纹：抹平「抓取时刻 / 时效状态」，只认榜单内容是否变化。"""
    for pat in VOLATILE_LINES:
        text = pat.sub("| - | - |", text)
    return trace.fingerprint(text)


def append_report_trace(date, text, trace_path=TRACE_PATH):
    """日报「变化即追加」留档：一份日报 Markdown -> report_trace.jsonl。

    覆盖写 ``五平台人气共振_日报_<口径日>.md`` 只留当日终态，这里把**每次变化后的日报全文**
    追加进 JSONL，历史永不覆盖；正文与末行相同则跳过。返回 ``(是否追加, 说明文本)``。
    """
    fp = report_fingerprint(text)
    record = {"key": date, "fingerprint": fp,
              "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "chars": len(text), "markdown": text}
    return trace.append_if_changed(trace_path, record, fp)


def main():
    ap = argparse.ArgumentParser(description="五平台人气共振 -> 每日 Markdown 日报")
    ap.add_argument("--snapshot", default=os.path.join(HERE, SNAP_NAME), help="快照路径")
    ap.add_argument("--date", default=None, help="覆盖口径日 YYYY-MM-DD（默认取快照内 date）")
    ap.add_argument("--out", default=None, help="输出文件（默认 五平台人气共振_日报_<口径日>.md）")
    ap.add_argument("--top", type=int, default=15, help="共振榜展示条数（默认 15）")
    args = ap.parse_args()

    if not os.path.exists(args.snapshot):
        print("错误: 快照不存在 %s（保留上一轮日报）" % args.snapshot)
        return 1

    snap, date = tx.load_snapshot(args.snapshot, args.date)
    stamp = tx.to_stamp(date)
    if stamp is None:
        print("错误: 口径日 %r 解析不出 8 位数字" % date)
        return 1

    items = tx.score_all(snap)
    if not items:
        print("错误: 快照里没有任何榜单数据（保留上一轮日报）")
        return 1

    seen = fetcher.load_seen(date)
    cache = load_json(os.path.join(HERE, JYGS_CACHE_NAME), default={}) or {}
    jygs_meta = cache.get(date) or None

    L, items, dist, resonance, n_jygs = build_report(snap, date, stamp, args.top,
                                                     seen, jygs_meta)
    text = "\n".join(L) + "\n"
    out = args.out or os.path.join(HERE, "五平台人气共振_日报_%s.md" % date)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)                                    # 覆盖写：当日终态
    _appended, trace_msg = append_report_trace(date, text)
    print("日报轨迹：%s" % trace_msg)

    full5 = sum(1 for it in items if it["cover"] >= 6.0)
    print("日报: 覆盖 %d 只 加权覆盖>=2 的 %d 只 五平台共振 %d 只 韭研红股 %d 只 百度热搜命中 %d 只"
          % (len(items), resonance, full5, n_jygs, len(snap.get("baidu") or {})))
    print("加权平台数分布: " + "  ".join("%.1f平台=%d" % (n, dist.get(n, 0))
                                         for n in sorted(dist, reverse=True)))
    print("输出:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
