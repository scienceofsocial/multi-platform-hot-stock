# -*- coding: utf-8 -*-
"""人气数据「变化即追加」落盘工具：JSONL 追加，历史永不覆盖。

为什么需要
----------
改造前，人气相关的产物全部是**同日覆盖写**：

* ``_hot_archive/hot_YYYY-MM-DD.json`` —— 同一口径日反复运行，后写覆盖前写
* ``a_duopingtai_hot_factor.csv``       —— 同一口径日先删旧行再整日重写
* ``五平台人气共振_日报_YYYY-MM-DD.md`` —— 每轮整份覆盖

覆盖写只留「当日终态」，**丢掉了「人气何时、怎么变化」的过程**，回测样本也永远只有
「每个口径日一帧」。本模块提供统一的**变化检测 + JSONL 追加**：只有榜单内容真的变了才
追加一行，既留下完整变化轨迹，又不会因每 10 分钟一轮而灌入大量重复行。
（当日终态文件仍照旧覆盖写，两种形态并存、互不影响。）

落盘位置
--------
``_hot_archive/`` 下三份 trace，一行 = 一次榜单变化：

================================  ==========================  ==============================
文件                               追加者                      一行 =
================================  ==========================  ==============================
``hot_trace.jsonl``               a_archive_hot_snapshot.py   一份全量快照
``factor_trace.jsonl``            a_duopingtai_hot_factor.py  该口径日的整日明细行
``report_trace.jsonl``            a_report_daily.py           一份日报 Markdown 全文
================================  ==========================  ==============================

每行固定含 ``key``（口径日）/ ``fingerprint``（内容指纹）/ ``generated_at``（追加时刻）
三个元字段，其余字段由调用方决定；``fingerprint`` 只覆盖**榜单内容**，故 ``fetched_at``
之类的「每轮必变」字段不会造成假追加。查轨迹（本机 duckdb / grep 均可）::

    python -c "import hot_trace,os;print(hot_trace.count_lines(os.path.join(hot_trace.TRACE_DIR,'hot_trace.jsonl')))"
"""
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
#: 轨迹落盘目录（与「当日终态」归档同目录）
TRACE_DIR = os.path.join(HERE, "_hot_archive")

#: 每轮刷新都会变、与榜单内容无关的元字段（参与指纹会把「无变化」误判成变化）
VOLATILE_KEYS = ("fetched_at",)

#: 读末行时最多回读的字节数（快照一行约 16 KB，留足余量）
TAIL_BYTES = 512 * 1024


def fingerprint(obj):
    """对象 -> sha1 指纹（键排序 + 紧凑分隔符：同内容必得同指纹）。"""
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def snapshot_fingerprint(snapshot):
    """快照 -> 榜单指纹：剔除 VOLATILE_KEYS，只认榜单内容。"""
    return fingerprint({k: v for k, v in snapshot.items() if k not in VOLATILE_KEYS})


def read_last(path):
    """读 JSONL 末行（只回读文件尾部、不整文件加载）；不存在/为空/损坏返回 None。"""
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        if os.path.getsize(path) > TAIL_BYTES:
            fh.seek(-TAIL_BYTES, os.SEEK_END)
            fh.readline()                       # 丢弃可能被截断的首行
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def append_if_changed(path, record, fp):
    """变化才追加一行；与末行「同 key 且同指纹」时跳过。

    返回 ``(是否已追加, 说明文本)``，说明文本可直接打印进日志。
    ``record`` 须自带 ``key``（口径日）。
    """
    last = read_last(path)
    name = os.path.basename(path)
    if last and last.get("key") == record.get("key") and last.get("fingerprint") == fp:
        return False, "内容无变化（%s 末行同 key 同指纹），跳过追加" % name
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:       # 追加：历史永不覆盖
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True, "内容有变化，已追加 1 行 -> %s" % os.path.relpath(path, HERE)


def count_lines(path):
    """JSONL 行数（看轨迹累积规模）；文件不存在记 0。"""
    if not os.path.exists(path):
        return 0
    with open(path, "rb") as fh:
        return sum(1 for ln in fh if ln.strip())
