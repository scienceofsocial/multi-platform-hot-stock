# -*- coding: utf-8 -*-
"""某口径日「某一榜」的全天变化时点明细表（读 ``_hot_archive/hot_trace.jsonl``）。

为什么需要
----------
``hot_trace.jsonl`` 是「变化即追加」的快照轨迹（一行 = 一次变化），落盘时只记「哪一轮变了」，
**不回答「几点变的、变了多少、进谁出谁」**。于是每次要排查「某榜何时定型 / 午休是否冻结 /
名单在某个时点从哪来」，都得临时写脚本 diff。本工具把这件事固化成一条命令。

判定口径
--------
* 轨迹一行 = 一次**任意平台**变化（指纹覆盖整份快照），所以一跳里目标榜**可能根本没变**
  —— 本表以**相邻两轮的目标榜内容**做 diff，逐跳标注「变 / 未变」，并按 5 个时段分组。
* ``进`` = 本轮新增的代码；``出`` = 本轮消失的代码；
  ``换位`` = 两轮都在、但 ``rank``/``name`` 值不同的代码（成分不变、名次互换）。
* 首轮只报只数、标 ``INIT``（无前值可比）。

用法
----
::

    python hot_trace_timeline.py                                  # 最新口径日 · sj88.ld
    python hot_trace_timeline.py --board sj88.rb                  # 换成 55188 人气榜
    python hot_trace_timeline.py --key 2026-09-24 --until 14:40:59 # 截到盘中某时刻（回溯当日当时视角）
    python hot_trace_timeline.py --csv _tmp_ld_timeline.csv       # 导出逐轮 CSV（含未变轮）
"""
import argparse
import csv
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
TRACE = os.path.join(HERE, "_hot_archive", "hot_trace.jsonl")

#: 时段切分（左闭右开，按 generated_at 的 HH:MM:SS）；
#: 11:40 起归「午休」、15:00 起归「盘后」，与交易时段对齐
SESSIONS = (
    ("盘前", "00:00:00", "09:30:00"),
    ("早盘", "09:30:00", "11:40:00"),
    ("午休", "11:40:00", "13:00:00"),
    ("午后", "13:00:00", "15:00:00"),
    ("盘后", "15:00:00", "24:00:00"),
)


def load(path):
    """读 JSONL 轨迹（整文件，一行一条）。"""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def dig(snapshot, board):
    """按 ``sj88.ld`` 取到子榜；缺失返回 ``None``。"""
    cur = snapshot
    for part in board.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def entries(board_val):
    """子榜 -> 有序 ``[(code, val), ...]``；dict 与 list 两种形态都吃。"""
    if isinstance(board_val, dict):
        return list(board_val.items())
    if isinstance(board_val, list):
        return [(c, None) for c in board_val]
    return []


def sort_key(item):
    """上榜顺序：dict 取 rank（缺 rank 排最后），list 用原顺序（榜本身就是名次序）。

    ``item`` 为 ``(idx, (code, val))``；list 形态时 ``val`` 为 ``None``，直接按 ``idx`` 排。

    rank 并列时**不再**附加 code 做 tiebreaker —— Python 的 ``sorted`` 稳定，并列者保留榜内
    原始插入序，与页面上的 top3 一致；加 code 键会把并列名次按代码字典序打乱
    （55188 龙头榜首行就是 ``SZ002614`` 与 ``SH600815`` 并列 rank=1，加 code 会让
    ``SH600815`` 反超到第一）。
    """
    idx, (code, val) = item
    if isinstance(val, dict):
        rank = val.get("rank")
        return (0, rank if isinstance(rank, int) else 10 ** 6)
    return (1, idx)


def ordered(board_val):
    """子榜 -> 按名次排好的 ``[code, ...]``。"""
    return [c for _, (c, _) in sorted(enumerate(entries(board_val)), key=sort_key)]


def label(code, val):
    """``SZ002614(奥佳华·龙1)`` 形式的小标签；list 榜只有代码。"""
    if isinstance(val, dict):
        name = val.get("name") or "?"
        rank = val.get("rank")
        return "%s(%s·龙%s)" % (code, name, rank) if isinstance(rank, int) else "%s(%s)" % (code, name)
    return code


def session_of(t):
    hhmmss = t[11:19] if len(t) >= 19 else "00:00:00"
    for name, lo, hi in SESSIONS:
        if lo <= hhmmss < hi:
            return name
    return "盘后"


def diff(prev, cur):
    """相邻两轮的目标榜 -> ``(进列表, 出列表, 换位列表)``（均已按当前轮名次排序）。"""
    p, c = dict(entries(prev)), dict(entries(cur))
    inn = [k for k in ordered(cur) if k not in p]
    out = [k for k in ordered(prev) if k not in c]
    moved = [k for k in ordered(cur) if k in p and p[k] != c[k]]
    return inn, out, moved


def build(rows, board, top_n, until=None):
    """轨迹 -> 逐轮行；``until`` 形如 ``14:40:59``（含）用于回溯当日盘中视角。"""
    seq = []
    for r in rows:
        stamp = str(r.get("generated_at") or "")
        if until and stamp[11:19] > until:
            continue
        seq.append((stamp, dig(r.get("snapshot") or {}, board)))
    out = []
    for i, (stamp, val) in enumerate(seq):
        prev = seq[i - 1][1] if i else None
        if i == 0:
            inn = out_c = moved = []
        else:
            inn, out_c, moved = diff(prev, val)
        top_codes = ordered(val)[:top_n]
        out.append({
            "round": i,
            "generated_at": stamp,
            "session": session_of(stamp),
            "changed": i > 0 and (inn or out_c or moved),
            "n_before": len(entries(prev)) if i else None,
            "n_after": len(entries(val)),
            "n_in": len(inn), "n_out": len(out_c), "n_moved": len(moved),
            "in_codes": inn, "out_codes": out_c, "moved_codes": moved,
            "top_codes": top_codes,
            "top": [label(c, dict(entries(val))[c]) for c in top_codes],
        })
    return out


def report(rows, board, path, key):
    """打印时点明细表 + 未变时点 + 小结。"""
    changed = [r for r in rows if r["changed"]]
    init, rest = rows[0], rows[1:]
    counts = [r["n_after"] for r in rows]
    print("轨迹文件: %s" % os.path.relpath(path, HERE))
    print("口径日  : %s（共 %d 条轨迹 = 1 条 INIT + %d 个抓取轮）" % (key, len(rows), len(rest)))
    print("目标榜  : %s   只数 %s -> %s（min %d / max %d）" % (
        board, init["n_after"], rows[-1]["n_after"], min(counts), max(counts)))
    print("变化分布: 变了 %d 轮 / 未变 %d 轮" % (len(changed), len(rest) - len(changed)))
    print()

    for name, _, _ in SESSIONS:
        seg = [r for r in rows if r["session"] == name]
        if not seg:
            continue
        seg_chg = [r for r in seg if r["changed"]]
        print("=== %s（%s ~ %s）变化 %d 次 / 该段 %d 轮 ===" % (
            name, seg[0]["generated_at"][11:19], seg[-1]["generated_at"][11:19],
            len(seg_chg), len(seg)))
        print(" %-4s %-10s %-12s %s" % ("#", "时刻", "只数", "进/出/换位   龙头 top3"))
        if not seg_chg:
            print("  —— 该段无变化（榜单冻结）——")
        for r in seg_chg:
            print(" %-4d %-10s %-12s %-12s %s" % (
                r["round"], r["generated_at"][11:19],
                "%s→%s" % (r["n_before"], r["n_after"]) if r["n_before"] is not None else "→%s" % r["n_after"],
                "进%d 出%d 换位%d" % (r["n_in"], r["n_out"], r["n_moved"]),
                ", ".join(r["top"]) or "—"))
        print()

    flat = [r for r in rest if not r["changed"]]
    print("=== 未变时点（%d 轮，轨迹因别的平台变化而追加，本榜一字未动）===" % len(flat))
    print(" " + ", ".join(r["generated_at"][11:19] for r in flat) if flat else " 无")
    print()

    print("=== 小结 ===")
    if changed:
        busiest = max(changed, key=lambda r: r["n_in"] + r["n_out"] + r["n_moved"])
        print(" 最大换血: %s  进%d 出%d 换位%d（n %s→%s）" % (
            busiest["generated_at"][11:19], busiest["n_in"], busiest["n_out"],
            busiest["n_moved"], busiest["n_before"], busiest["n_after"]))
    if len(changed) > 1:
        gap = min(((changed[i]["generated_at"], changed[i + 1]["generated_at"])
                   for i in range(len(changed) - 1)),
                  key=lambda p: _secs(p[1]) - _secs(p[0]))
        print(" 最密两轮: %s → %s（相隔 %d 秒）" % (gap[0][11:19], gap[1][11:19], _secs(gap[1]) - _secs(gap[0])))
    run = best = 0
    start = span = None
    for r in rest:
        if r["changed"]:
            run = 0
            continue
        if run == 0:
            start = r["generated_at"]
        run += 1
        if run > best:
            best, span = run, (start, r["generated_at"])
    if span:
        print(" 最长静默: %s → %s（连续 %d 轮未变、%d 分钟）" % (
            span[0][11:19], span[1][11:19], best, (_secs(span[1]) - _secs(span[0])) // 60))


def _secs(stamp):
    t = stamp[11:19] if len(stamp) >= 19 else "00:00:00"
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def render_md(rows, board, key, label="龙头榜"):
    """逐轮行 -> 「变化时点」独立 Markdown（供 a_render_ld_timeline.py 每 10 分钟刷一遍）。

    与 ``report()`` 的差别（按用户口径定稿）：

    * **扁平**、按时间顺序，不按 5 个时段分组；
    * **只列变了的那几轮**，编号从 1 起（未变轮不占号、不展示）；
    * 首行 = INIT（只数无前值可比的 `n_before`，不编号，``#`` 列记 ``—``）；
    * 「形态」只写 ``进X 出Y 换位Z``，**不加**中文备注（如「整榜清空」属人工标注，无法机械复现）；
    * 「龙头 top3」只写纯代码，不写 ``(名称·龙N)``。
    """
    changed = [r for r in rows if r["changed"]]
    init = rows[0]
    lines = [
        "# %s 变化时点_%s" % (label, key),
        "",
        "## %d 个变化时点（实测，按时间顺序）" % len(changed),
        "",
        "| # | 时刻 | 只数 | 形态（进/出/换位） | 龙头 top3 |",
        "|---|---|---|---|---|",
        "| — | %s(INIT) | %d | 初始 | %s |" % (
            init["generated_at"][11:19], init["n_after"],
            ",".join(init["top_codes"]) or "—"),
    ]
    for i, r in enumerate(changed, 1):
        lines.append("| %d | %s | %s → %s | 进%d 出%d 换位%d | %s |" % (
            i, r["generated_at"][11:19], r["n_before"], r["n_after"],
            r["n_in"], r["n_out"], r["n_moved"],
            ",".join(r["top_codes"]) or "—"))
    lines.append("")
    return "\n".join(lines) + "\n"


def export(rows, path, board):
    """逐轮 CSV（含未变轮），便于后续在 Excel / duckdb 里二次统计。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["round", "generated_at", "session", "changed", "board",
                    "n_before", "n_after", "n_in", "n_out", "n_moved",
                    "in_codes", "out_codes", "moved_codes", "top"])
        for r in rows:
            w.writerow([r["round"], r["generated_at"], r["session"],
                        int(bool(r["changed"])), board, r["n_before"], r["n_after"],
                        r["n_in"], r["n_out"], r["n_moved"],
                        ",".join(r["in_codes"]), ",".join(r["out_codes"]),
                        ",".join(r["moved_codes"]), ",".join(r["top"])])
    return path


def main():
    ap = argparse.ArgumentParser(description="hot_trace 某榜全天变化时点明细表")
    ap.add_argument("--trace", default=TRACE, help="轨迹文件（默认 _hot_archive/hot_trace.jsonl）")
    ap.add_argument("--key", default=None, help="口径日，默认取文件最后一个")
    ap.add_argument("--board", default="sj88.ld", help="目标榜，如 sj88.ld / sj88.rb / sj88.zl / em")
    ap.add_argument("--until", default=None, help="只取 <= 该 HH:MM:SS 的轮次（回溯盘中视角）")
    ap.add_argument("--top", type=int, default=3, help="每轮展示的龙头条数（默认 3）")
    ap.add_argument("--csv", default=None, help="另存逐轮明细 CSV")
    args = ap.parse_args()

    rows = load(args.trace)
    key = args.key or rows[-1]["key"]
    rows = [r for r in rows if r["key"] == key]
    if not rows:
        print("口径日 %s 无轨迹记录" % key)
        return 1
    timeline = build(rows, args.board, args.top, args.until)
    report(timeline, args.board, args.trace, key)
    if args.csv:
        print("\nCSV 已写出: %s（%d 行）" % (export(timeline, args.csv, args.board), len(timeline)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
