# -*- coding: utf-8 -*-
"""``a_render_ld_timeline.py`` 表格里「当前显示的那 3 个」龙头 -> 追加进通达信自选板块 ``.blk``。

为什么需要
----------
``a_render_ld_timeline.py`` 产出的《龙头榜_变化时点_YYYY-MM-DD.md》每行末尾就是该轮的
「龙头 top3」（纯代码）。盯盘时想把「这几个时点分别进了哪几只」留成通达信自选板块，
手工抄既慢又容易错。本脚本把这一步固化：读**同一条轨迹** `_hot_archive/hot_trace.jsonl`
-> 取表格**最后一个展示行**的 3 个代码 -> 按 .blk 格式**追加**进指定板块文件。

与老程序 a_export_tdx_hot_rank.py 的关系
---------------------------------------
老程序也写 ``blocknew\\55188.blk``（55188 三榜并集、按共振分降序），但只在**当日第一轮**
整份重写一次（清空一次、落当日基准），其后各轮改为**追加** —— 故本脚本追加进 55188.blk
的内容不会被老程序抹掉，两边可以共用同一个板块文件：
55188 板块 = 老程序的三榜并集 + 本脚本在各定点时刻追加的「当前显示的 top3」。
本脚本只**追加、不重写、不清空**任何 .blk。

「显示的 3 个」怎么取
--------------------
md 表只展示**变了的那几轮**（外加首行 INIT，未变轮不占号、不展示）。故本脚本取
「最后一个变化时点」那一行的 top3；当日尚无变化时退回 INIT 行。取不到任何代码
（该轮是空榜、或代码形态认不出）时**不写文件**、打印 ``SKIP``、返回 0（不是错误）。
同一个时点被多次采集时会**重复追加**，这是有意为之（按用户口径：只在末尾追加）。

追加格式
--------
沿用老程序实测的 .blk 格式：每只股票一段 ``CRLF + 市场位 + 6位代码``
（市场位 1=沪 0=深 2=北，与 ``_MKT_NO`` / .dat 文件名前缀同一约定）；GBK 编码、
无表头无注释、二进制写（免得文本模式把 ``\\n`` 二次翻译）。本脚本用 ``"ab"`` 追加，
**不清空已有成分**。

用法
----
::

    python a_export_ld_top3_blk.py                                        # -> 551883.blk
    python a_export_ld_top3_blk.py --blk C:\\new_tdx\\T0002\\blocknew\\55188.blk
    python a_export_ld_top3_blk.py --board sj88.rb                        # 换成 55188 人气榜
    python a_export_ld_top3_blk.py --blk _tmp.blk                          # 试跑（不碰通达信）
"""
import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import hot_trace_timeline as tl                                            # noqa: E402

#: instrument 市场前缀 -> 通达信市场位（决定 .blk 每行首位的数字）
MKT_NO = {"SH": 1, "SZ": 0, "BJ": 2}

#: 默认目标：程序一的 551883 板块（程序二在 bat 里显式指定 55188.blk）
BLK_DEFAULT = r"C:\new_tdx\T0002\blocknew\551883.blk"


def to_blk_line(inst):
    """轨迹里的 instrument -> .blk 行（市场位 + 6 位代码）；认不出返回 ``None``。

    轨迹 sj88 的键是 ``SH600189`` 这种市场前缀写法，兼容 ``600189.SH`` 写法。
    """
    if "." in inst:
        code, _, mkt = inst.partition(".")
    else:
        mkt, code = inst[:2], inst[2:]
    no = MKT_NO.get(mkt.upper())
    if no is None or len(code) != 6 or not code.isdigit():
        return None
    return "%d%s" % (no, code)


def pick_shown(timeline):
    """逐轮行 -> 表格里**最后一个展示出来的**行（变化时点；当日无变化则 INIT）。

    未变轮虽然也在轨迹里，但 md 不展示它们，故不算「显示出来的」。
    """
    shown = [r for r in timeline if r["changed"]]
    return (shown[-1], len(shown)) if shown else (timeline[0], 0)


def append_blk(path, lines):
    """把 ``lines`` 追加进 .blk（GBK、每行前置 CRLF）；返回写入行数。"""
    if not lines:
        return 0
    with open(path, "ab") as fh:
        fh.write("".join("\r\n" + k for k in lines).encode("gbk"))
    return len(lines)


def main():
    ap = argparse.ArgumentParser(description="把变化时点表最后一行展示的龙头 top3 追加进 .blk")
    ap.add_argument("--blk", default=BLK_DEFAULT, help="目标 .blk（追加；默认 551883.blk）")
    ap.add_argument("--trace", default=tl.TRACE, help="轨迹文件（默认 _hot_archive/hot_trace.jsonl）")
    ap.add_argument("--key", default=None, help="口径日，默认取轨迹最后一行的 key")
    ap.add_argument("--board", default="sj88.ld", help="目标榜（默认 55188 龙头榜）")
    ap.add_argument("--top", type=int, default=3, help="每轮展示的龙头条数（默认 3）")
    args = ap.parse_args()

    rows = tl.load(args.trace)
    if not rows:
        print("轨迹文件为空（%s），跳过" % os.path.relpath(args.trace, HERE))
        return 0
    key = args.key or rows[-1]["key"]
    day = [r for r in rows if r.get("key") == key]
    if not day:
        print("口径日 %s 无轨迹记录，跳过" % key)
        return 0
    day.sort(key=lambda r: str(r.get("generated_at") or ""))   # 轨迹本就时序追加，防御性排序

    timeline = tl.build(day, args.board, args.top)
    row, ordinal = pick_shown(timeline)
    codes = row["top_codes"]
    tag = "变化时点 #%d" % ordinal if ordinal else "INIT"
    lines = [to_blk_line(c) for c in codes]
    bad = [c for c, l in zip(codes, lines) if not l]
    good = [l for l in lines if l]
    if not good:
        print("SKIP - %s %s（%s）%s 无可用代码，未写文件" % (
            key, row["generated_at"][11:19], tag, args.board))
        return 0

    try:
        n = append_blk(args.blk, good)
    except OSError as e:                      # 通达信偶尔占用该文件，下个时点会再来一次
        print("警告: 追加 %s 失败（%s）" % (args.blk, e))
        return 1

    print("OK - %s %s（%s）龙头 top%d %s -> 追加 %d 行到 %s（现 %d 字节）%s" % (
        key, row["generated_at"][11:19], tag, len(codes), ",".join(codes) or "—",
        n, args.blk, os.path.getsize(args.blk),
        "；跳过认不出的 %s" % ",".join(bad) if bad else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
