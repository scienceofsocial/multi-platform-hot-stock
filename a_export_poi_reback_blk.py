# -*- coding: utf-8 -*-
"""POI「重回 · 同花顺#N」的股票 -> 追加进通达信自选板块 ``blocknew\\551881.blk``。

用途
----
同花顺指标平台（poi）的「重回」票 —— 当日**不是第一次**上人气榜、属于「上过又回来」的 ——
在主项目日志 ``hot_rank_daily.log`` 里会被标成

      SZ002286   保龄宝        [重回 · 首次 06:51:42]   同花顺#2

（由 ``a_fetch_hot_snapshot.py`` 的 ``report_new()`` 写出）。本脚本把这些票**追加**进
通达信自选板块 551881.blk，盯盘时直接当一个现成板块用，省去手工抄。

筛选口径
--------
取**目标口径日**日志里同时满足

* 标签以「重回」开头（``[重回 · 首次 HH:MM:SS]``；「新出现」不算），且
* 平台串里**有同花顺那一段**（``同花顺#2``；多平台并列如 ``同花顺#1 · 55188#1``、
  ``同花顺#14 · 通达信#20``，只要含同花顺即算）

的明细行。口径日按**轮头**日期（``[周四 2026/09/24  6:50:43.04] ===== START ...``）归属，
故默认「今天」= 本地日期，与「当日首轮」的判定同一把尺子。同日同一只票重复出现
（当日多轮反复上/下榜）只落一行。

551881.blk 的维护口径
---------------------
与 ``a_export_tdx_hot_rank.py`` 写 55188.blk 的做法一字不差：

* **当日第一轮整份重写**（``"wb"``，= 清空一次、落当日基准）；
* 其后各轮只把文件里**还没有的**新增成分追加到末尾（``"ab"`` + 读回已有成分查重），
  掉出榜单的仍留在板块里 —— 不用手工清理，也不会每轮把同一只票重复追加一遍。

「当日第一轮」按目标文件 mtime 是否在**今天 00:00 之后**判断（同老程序）；文件不存在也算。
当日一条都没有时**不写文件**（不清空），返回 0。

文件格式（实测）
----------------
``C:\\new_tdx\\T0002\\blocknew\\<名>.blk``：无表头无注释，开头一个 CRLF，随后每只股票一段
``CRLF + 市场位 + 6 位代码``；市场位 **1=沪 0=深 2=北**；**GBK** 编码，必须二进制读写
（文本模式会把 ``\\n`` 二次翻译）。

用法
----
::

    python a_export_poi_reback_blk.py                    # 今天 -> 551881.blk
    python a_export_poi_reback_blk.py --date 2026-09-24  # 指定口径日
    python a_export_poi_reback_blk.py --blk _tmp.blk     # 试跑（不碰通达信）
    python a_export_poi_reback_blk.py --log other.log    # 换日志

⚠ 数据源现状
------------
``同花顺#N`` 明细自 **2026-09-25** 起不再写进 ``hot_rank_daily.log``（``flat_ranks()`` 只播报
5 个计分平台，同花顺已归入「仅留档、不参与任何播报」）。故对 2026-09-25 及其后的日期，
本脚本会打印 ``SKIP``、不写盘；要恢复产出需改数据源（如改用 ``last_good.json`` 的
``ths_poi`` 列表），本脚本不做这件事。
"""
import argparse
import os
import re
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))

#: 输入：主项目日志（a_fetch_hot_snapshot.py 写「新出现 / 重回」标签的唯一落点）
LOG_DEFAULT = os.path.join(HERE, "hot_rank_daily.log")

#: 输出：通达信自选板块 551881（已在 blocknew.cfg 注册）
BLK_DEFAULT = r"C:\new_tdx\T0002\blocknew\551881.blk"

#: 日志里的市场前缀 -> 通达信市场位（.blk 每行首位）
MKT_NO = {"SH": 1, "SZ": 0, "BJ": 2}

#: 平台串里各平台的分隔符（a_fetch_hot_snapshot.py 用 " · " 连接）
PLAT_SEP = " · "

#: 轮头 / 明细行 —— 与 pre_market_view.py 同一套正则
#: 轮头形如 ``[周四 2026/09/24  6:50:43.04] ===== START hot rank export =====``（小时位可 1 位）
ROUND_RE = re.compile(r"^\[周.\s+(\d{4})/(\d{2})/(\d{2})\s+(\d{1,2}):(\d{2}):(\d{2})")
#: 明细形如 ``  SZ002286   保龄宝        [重回 · 首次 06:51:42]   同花顺#2``
LINE_RE = re.compile(r"^\s+([A-Z]{2}\d{6})\s+(.+?)\s+\[(.+?)\]\s+(.+?)\s*$")


def to_blk_key(code):
    """日志里的带前缀代码（``SZ002286``）-> .blk 行（``市场位 + 6 位代码``）；认不出返回 ``None``。"""
    mkt, num = code[:2], code[2:]
    no = MKT_NO.get(mkt)
    if no is None or len(num) != 6 or not num.isdigit():
        return None
    return "%d%s" % (no, num)


def has_ths(plats):
    """平台串里是否有「同花顺」那一段（``同花顺#2`` / ``同花顺#1 · 55188#1`` 都算）。"""
    return any(seg.strip().startswith("同花顺") for seg in plats.split(PLAT_SEP))


def scan_log(path, date):
    """扫日志，返回口径日 ``date``（``YYYY-MM-DD``）的「重回 + 含同花顺」成分键。

    按日志出现顺序、同日去重；文件读不到返回空列表。
    """
    keys, seen, cur = [], set(), None
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError as e:
        print("警告: 读日志失败（%s）" % e)
        return []
    with fh:
        for raw in fh:
            head = ROUND_RE.match(raw)
            if head:
                cur = "%s-%s-%s" % head.group(1, 2, 3)
                continue
            if cur != date:
                continue
            m = LINE_RE.match(raw.rstrip("\r\n"))
            if not m:
                continue
            tag, plats = m.group(3), m.group(4)
            if not tag.startswith("重回") or not has_ths(plats):
                continue
            key = to_blk_key(m.group(1))
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def _day_start():
    """今天 00:00 的 Unix 时间戳，用来判断目标 .blk 是否已被「当日第一轮」写过。"""
    now = datetime.now()
    return datetime(now.year, now.month, now.day).timestamp()


def keys_existing(path):
    """读回 .blk 里已有的成分键（``市场位 + 6位代码``，7 字符）；读不到返回空集合。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return set()
    text = raw.decode("gbk", "ignore").replace("\r", "\n")
    return {ln for ln in text.split("\n") if len(ln) == 7 and ln.isdigit()}


def write_blk(path, keys):
    """落地目标 .blk：当日首轮整份重写、其后只追加新增。返回 ``(写入行数, 说明)``。

    二进制写入以免文本模式把 ``\\n`` 二次翻译成 CRLF；写入失败抛 ``OSError`` 由调用方告警。
    """
    try:
        first = os.path.getmtime(path) < _day_start()
    except OSError:
        first = True                  # 文件不存在/读不到 -> 当今天第一轮处理
    if first:
        todo, mode, note = keys, "wb", "当日首轮整份重写"
    else:
        have = keys_existing(path)
        todo = [k for k in keys if k not in have]
        mode, note = "ab", "追加新增"
    if todo:
        with open(path, mode) as f:
            f.write("".join("\r\n" + k for k in todo).encode("gbk"))
    return len(todo), note


def main():
    ap = argparse.ArgumentParser(description="POI「重回 · 同花顺#N」的股票 -> 追加进 551881.blk")
    ap.add_argument("--log", default=LOG_DEFAULT, help="主项目日志（默认同目录 hot_rank_daily.log）")
    ap.add_argument("--blk", default=BLK_DEFAULT, help=r"目标 .blk（默认 blocknew\551881.blk）")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                    help="口径日 YYYY-MM-DD（默认今天，按日志轮头日期）")
    args = ap.parse_args()

    keys = scan_log(args.log, args.date)
    if not keys:
        print("SKIP - %s 日志里没有「重回 · 同花顺#」的股票（或该日无此类记录），未写文件 -> %s"
              % (args.date, args.blk))
        return 0

    try:
        n, note = write_blk(args.blk, keys)
    except OSError as e:              # 通达信偶尔占用该文件，下一轮会自动补写
        print("警告: 写入 %s 失败（%s）" % (args.blk, e))
        return 1

    if not n:
        print("OK - %s 重回·同花顺 %d 只已全在板块内（%s） -> %s（现 %d 字节）"
              % (args.date, len(keys), note, args.blk, os.path.getsize(args.blk)))
        return 0
    print("OK - %s 重回·同花顺 %d 只 -> %s %d 行到 %s（现 %d 字节）"
          % (args.date, len(keys), note, n, args.blk, os.path.getsize(args.blk)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
