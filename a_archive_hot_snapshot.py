# -*- coding: utf-8 -*-
"""人气榜快照的**双写**归档：当日终态 + 变化即追加的历史轨迹。

为什么需要
----------
各人气榜接口**只返回当日榜、不可回溯**（唯一的例外是百度热搜，接口带
``day`` 参数可回补约 7 个交易日）。因此「多平台共振」的历史样本只能靠**前向累积**，
否则永远只有最近几天可用。本脚本一次运行写两份、互相补位：

1. ``_hot_archive/hot_YYYY-MM-DD.json`` —— **当日终态**。把 ``last_good.json``
   （连同 ``date`` 字段）原子复制过去；同一口径日反复运行 = 覆盖写（后写覆盖前写），
   盘后最后一次留下的就是该日「收盘后终态」。结构与 ``last_good.json`` 完全一致，
   可直接喂给::

       python a_duopingtai_hot_factor.py --snapshot _hot_archive/hot_2026-09-23.json

2. ``_hot_archive/hot_trace.jsonl`` —— **变化轨迹（JSONL 追加、永不覆盖）**。
   每 10 分钟一轮里，只有**榜单内容真的变了**才追加一行（``fetched_at`` 不参与
   指纹，故重复轮次不写）；一行 = 一份全量快照 + ``key``/``fingerprint``/
   ``generated_at``/``counts``。这样既保留「人气何时变、怎么变」的过程
   （回测可拿到日内多帧），又不会被刷屏式轮次灌入海量重复行。

用法
----
    python a_archive_hot_snapshot.py                      # 默认归档 last_good.json
    python a_archive_hot_snapshot.py --date 2026-09-22    # 强制指定口径日（慎用）
    python a_archive_hot_snapshot.py --snapshot x.json --dir D:\\hist

退出码
------
0 = 已归档（含「内容无变化，跳过追加」）；1 = 源文件缺失/损坏等硬错误。
（在 ``run_hot_rank_daily.bat`` 里按**容错**调用：归档失败只记 WARN，不阻断导出。）
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import hot_trace as trace                                           # noqa: E402
from a_fetch_hot_snapshot import (KPH_BOARDS, OUT_PATH, PLATFORMS,   # noqa: E402
                                  SCORING_PLATFORMS, SJ88_BOARDS, TGB_BOARD_KEYS)

#: 变化轨迹文件名（放在归档目录下，与「当日终态」文件并存）
TRACE_NAME = "hot_trace.jsonl"

#: 平台键 -> 子榜键（无子榜的平台不在表内）；与抓取脚本的常量保持同源
SUB_BOARDS = {
    "tgb": TGB_BOARD_KEYS,
    "kph": tuple(b[0] for b in KPH_BOARDS),
    "sj88": tuple(b[0] for b in SJ88_BOARDS),
}

DEFAULT_DIR = os.path.join(HERE, "_hot_archive")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def count_entries(snapshot, key):
    """某平台当日的条目数：有子榜的累加各子榜，其余直接数顶层键。"""
    node = snapshot.get(key)
    if not isinstance(node, dict):
        return None
    subs = SUB_BOARDS.get(key)
    if not subs:
        return len(node)
    return sum(len(node.get(s) or {}) for s in subs)


def valid_date(text):
    """``YYYY-MM-DD`` 且能解析；否则 None。"""
    s = str(text or "").strip()
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def archive(src, dest_dir, date_override=None, quiet=False, trace_name=TRACE_NAME):
    """归档一次；返回 (口径日, 目标路径, 条目数表, 是否追加轨迹)。

    写两份：``hot_<口径日>.json`` 覆盖写（当日终态）+ ``hot_trace.jsonl``
    变化即追加（榜单内容变了才写一行）。
    """
    if not os.path.exists(src):
        raise FileNotFoundError("快照文件不存在：%s" % src)
    with open(src, "r", encoding="utf-8") as fh:
        snapshot = json.load(fh)
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("快照内容为空或不是 JSON 对象：%s" % src)

    day = valid_date(date_override) or valid_date(snapshot.get("date"))
    if not day:
        day = dt.datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d")
        print("  [警告] 快照无有效 date 字段，回退用文件修改日期：%s" % day)

    counts = {key: count_entries(snapshot, key) for key, _label in PLATFORMS}

    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "hot_%s.json" % day)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False)
    os.replace(tmp, dest)

    # 变化轨迹：榜单内容变了才追加一行（fetched_at 不参与指纹，故重复轮次不写）
    fp = trace.snapshot_fingerprint(snapshot)
    record = {
        "key": day,
        "fingerprint": fp,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fetched_at": snapshot.get("fetched_at"),
        "counts": counts,
        "snapshot": snapshot,
    }
    appended, msg = trace.append_if_changed(os.path.join(dest_dir, trace_name), record, fp)

    # 覆盖率播报：某计分平台为 0 说明当日抓取异常，归档文件仍保留以便事后排查
    if not quiet:
        print("  %s" % msg)
        print("  口径日 %s  fetched_at=%s  -> %s"
              % (day, snapshot.get("fetched_at") or "-",
                 os.path.relpath(dest, HERE)))
        line = "  "
        for key, label in SCORING_PLATFORMS:
            line += "%s=%s  " % (label, counts[key] if counts[key] is not None else "-")
        print(line)
        empty = [label for key, label in SCORING_PLATFORMS if not counts[key]]
        if empty:
            print("  [警告] 以下平台当日条目为 0（抓取可能异常）：%s" % "、".join(empty))
    return day, dest, counts, appended


def summarize(dest_dir, trace_name=TRACE_NAME):
    """列出归档目录已覆盖的口径日，并播报变化轨迹的累积行数。"""
    if not os.path.isdir(dest_dir):
        return []
    days = sorted(f[4:-5] for f in os.listdir(dest_dir)
                  if f.startswith("hot_") and f.endswith(".json"))
    if days:
        print("  归档目录已覆盖 %d 个口径日：%s ~ %s"
              % (len(days), days[0], days[-1]))
    else:
        print("  归档目录尚无文件：%s" % dest_dir)
    print("  变化轨迹 %s 累计 %d 行"
          % (trace_name, trace.count_lines(os.path.join(dest_dir, trace_name))))
    return days


def main():
    ap = argparse.ArgumentParser(description="五平台人气榜快照 · 每日按口径日归档")
    ap.add_argument("--snapshot", default=OUT_PATH,
                    help="源快照路径；缺省用抓取脚本的 last_good.json")
    ap.add_argument("--dir", default=DEFAULT_DIR,
                    help="归档目录；缺省 <本脚本目录>\\_hot_archive")
    ap.add_argument("--date", default=None,
                    help="强制口径日 YYYY-MM-DD；缺省取快照的 date 字段")
    ap.add_argument("--quiet", action="store_true", help="只输出一行结果")
    args = ap.parse_args()

    try:
        day, dest, counts, appended = archive(args.snapshot, args.dir,
                                              date_override=args.date, quiet=args.quiet)
    except Exception as exc:                                # noqa: BLE001
        print("[归档失败] %s" % exc)
        return 1

    if args.quiet:
        print("[归档] %s -> %s  trace=%s"
              % (day, dest, "appended" if appended else "unchanged"))
    summarize(args.dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
