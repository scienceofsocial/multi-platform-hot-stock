# -*- coding: utf-8 -*-
"""五平台人气共振 -> 通达信「历史行情指标排序」动态指标。

数据来源：同目录 ``last_good.json``（a_fetch_hot_snapshot.py 抓的五平台人气榜前 20 快照；
         由 run_hot_rank_daily.bat 全天候每 10 分钟刷新一次）
输出：1) C:\new_tdx\T0002\signals\signals_user_1\<市场>_<代码>.dat
         （.901 自定义数据 · 数据号 1 = 共振分，8 字节/条 = int32 LE 日期 + float32 LE 分值；
           每只股票可能写两条 —— 口径日 + 本地日线里已存在的最后一个交易日，见下「日期戳」）
      2) C:\new_tdx\T0002\signals\signals_user_2..9\<市场>_<代码>.dat
         （数据号 2/3/7/8/9 = 五个平台各自的**名次分贡献**，五列相加 = 共振分里的名次分部分；
           数据号 4/5/6 弃用留空、不再写入；号段不重排）
      3) 五平台人气共振_通达信排序指标.txt（通达信排序公式源码，粘一次永久不用再改）
      4) C:\new_tdx\T0002\blocknew\55188.blk
         （通达信「自选板块」55188：55188 三榜 主力排名/人气热榜/龙头 的并集，按共振分降序；
           当日**第一轮**整份重写（= 清空一次、落当日基准），其后各轮只把文件里还没有的
           **新增成分**追加到末尾（对已有内容去重，同一只股票一天只落一行）
           -> 新上榜自动加入、掉榜的仍留在板块里，不用再手工维护这个 .blk 文件）

打分口径
--------
    共振分     = 加权覆盖平台数 x 1000 + Σ_榜单 max(0, 21 - 该榜单名次) x 该榜平台权重 + 韭研红股 120
    覆盖平台数 = 上榜平台的**加权**去重数（东方财富/淘股吧/开盘啦/55188/韭研公社；
                 **55188 记 2.0**、其余记 1.0，故理论满配 = 6.0）
    榜单得分   = 55188 主力/人气/龙头各是不同榜单、各自计分相加（三榜名次分各 x3、
                 合计最高 180 分）；开盘啦只取「复盘人气榜」一榜（原盘中榜已去掉，最高 20 分）；
                 淘股吧实时/24h 取该平台内最好名次（只计 1 次）；
                 韭研公社异动图红股是图片识别结果、没有名次，让加权覆盖平台数 +1，
                 并固定贡献 120 分（与 55188 三榜同等）

1000 的权重保证「多覆盖一个整平台」一定排在「少一个平台」之前：名次分上限 360
（6 张计分榜加权后 240 + 韭研红股 120）远小于 1000，故共振分排序严格单调。
INTPART(共振分/1000) 可反推平台档位 —— 与旧「五平台人气交叉」公式、tdx_paixu.py 的
f_renqi 兼容，公式与 Python 侧都不用改。

与 a_duopingtai_hot_factor.py 的 420 量级因子相比，加权覆盖平台数与名次分的算法一字不差
（直接 ``import`` 复用其 ``score_parts``，再由 ``PLATFORM_BOARDS / PLATFORM_FIELD / RANK_BASE``
兜底），只把平台数权重由 420 换成 1000，从而不破坏通达信既有公式（排序先后关系不变）。

⚠ 数据号 1 是「五平台人气交叉」在用同一条通道，本脚本接管后该通道即为五平台口径，
  旧 RENQI 公式不变也会跟着变成新口径（排序名次总体稳定，个别股票平台数会变）。

日期戳 / 盘前可见
-----------------
SIGNALS_USER(n, 2) 是「该周期没有数据就返回 0」，即按**每根K线的日期**去 .dat 里精确取值。
而 vipdoc 日线由「盘后数据下载」落盘，开盘前它仍停在上一交易日 —— 若只写口径日这一条，
盘前（乃至当天第一根K线出现前）排序指标会全读成 0。
故本脚本每只股票写**两条**记录：口径日 + 本地日线里已存在的最后一个交易日（上证指数
``vipdoc\sh\lday\sh000001.day`` 的末条日期，读不到则退化为只写口径日）。
效果：盘前立刻显示在上一交易日那根K线上，当天K线一出现又自动显示当天的值，无需任何时间判断。
收盘后本地日线补上当日行情时两天相同，自动回到单条记录。

用法
----
    python a_export_tdx_hot_rank.py                     # 读 last_good.json 并刷新 .dat
    python a_export_tdx_hot_rank.py --snapshot x.json   # 指定快照
    python a_export_tdx_hot_rank.py --date 2026-09-18   # 覆盖口径日（默认取快照内 date）

免粘贴 / 动态变化
----------------
分值不进公式、只进 .dat：换榜单、换日期都只动数据文件。每轮整份重写（幂等覆盖）而不是追加，
因为通达信在 .901 里点「保存」时会拿内存里的旧副本回写这些 .dat，追加的记录会被抹掉；
每 10 分钟重写一次即自动修复。
"""
import argparse
import json
import os
import re
import struct
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 五平台口径的唯一实现：score_parts / PLATFORM_BOARDS / PLATFORM_FIELD / RANK_BASE / collect_best_ranks
import a_duopingtai_hot_factor as hot                                         # noqa: E402

JSON_PATH = os.path.join(HERE, "last_good.json")
OUT = os.path.join(HERE, "五平台人气共振_通达信排序指标.txt")
FNAME = "RENQI8"        # 通达信公式名称（沿用历史名，避免用户重贴公式；与旧 RENQI 读同一数据号）

#: 平台数权重：名次分上限 360（6 张榜加权后 240 + 韭研红股 120），远小于 1000，
#: 故平台档位一定是第一排序键
COVER_WEIGHT = 1000

# 通达信 .901「自定义数据管理器」的数值序列通道（外部直写，免手工粘贴）
SIG_NO = 1              # 共振分数据号（datacfg.dat 里的 1 = RQMAIN，属性=数值序列）
SIG_TYPE = 2            # SIGNALS_USER 的 TYPE=2：该周期没有数据则返回 0（排序用）
SIG_DIR_FMT = r"C:\new_tdx\T0002\signals\signals_user_%d"    # 数据号 -> 落地目录
SIG_DIR = SIG_DIR_FMT % SIG_NO                               # 共振分目录（日报用）
DATACFG = r"C:\new_tdx\T0002\signals\datacfg.dat"            # .901 数据号注册表
_DAT_RE = re.compile(r"^\d_\d{6}\.dat$")

#: 本地已下载K线的「最后一个交易日」来源：上证指数日线（32 字节/条 = 日期+OHLC+额+量+保留）
LDDAY = r"C:\new_tdx\vipdoc\sh\lday\sh000001.day"
LDDAY_FALLBACK = r"C:\new_tdx\vipdoc\sh\lday\sh600000.day"
_LDDAY_REC = 32

#: 逐平台名次分的数据号（一个数据号只能存一个数，故每个计分平台各占一号）：
#: (平台, 数据号, datacfg 里的名称)。数据号 1 保留给共振分，各平台贡献之和 = rank_score。
#: 数据号 4/5/6 已弃用（不重排号段、不再写入、公式也不读）。
PLATFORM_SIGS = [("东方财富", 2, "RQ8_EM"), ("淘股吧", 3, "RQ8_TGB"),
                 ("开盘啦", 7, "RQ8_KPH"),
                 ("55188", 8, "RQ8_SJ88"), ("韭研公社", 9, "RQ8_JYGS")]
#: 已弃用（不再写入）的数据号：4/5/6，管线每轮清掉其历史残留 .dat
DEPRECATED_SIGS = (4, 5, 6)
#: 公式里逐平台输出的变量名：表头即平台名；「55188」以数字开头不能作通达信变量名，
#: 故按本仓内部命名（sj88_*）缩写为 SJ88。
PLATFORM_VAR = {"东方财富": "东方财富", "淘股吧": "淘股吧", "开盘啦": "开盘啦",
                "55188": "SJ88", "韭研公社": "韭研公社"}

#: datacfg.dat 记录长度：int32 数据号 + int32 属性(1=数值序列) + 32B 名称 + 16B 单位 + int32
_DATACFG_REC = 60

#: instrument 后缀 -> 通达信市场号（决定 .dat 文件名前缀；.blk 的市场位也用同一约定）
_MKT_NO = {"SH": 1, "SZ": 0, "BJ": 2}

#: 通达信「自选板块」文件（板块名 55188 已在同目录 blocknew.cfg 里注册，只需改写内容）。
#: 当日**第一轮**整份重写（清空一次、落当日基准），其后各轮只把**文件里还没有**的新增成分
#: 追加到末尾（对文件已有内容去重）-> 新上榜自动加入、掉榜的仍留在板块里，不用再手工增删。
#: 本脚本每 10 分钟一轮、当日 00:00 就跑了第一轮，故正常一整天只有 00:00 那轮清空。
#: 程序二（a_export_ld_top3_blk.py）也往同一个文件追加它那 3 只（按用户口径不去重），
#: 故这里**不能每轮清空**，否则会把程序二刚追加的内容抹掉。
BLK_SJ88 = r"C:\new_tdx\T0002\blocknew\55188.blk"
#: 55188 板块的成分 = 快照 sj88 下这三张子榜的并集（与 a_fetch_hot_snapshot.py 的键一致）
SJ88_BOARDS = ("zl", "rb", "ld")


def to_stamp(date):
    """口径日 -> int(YYYYMMDD)；解析不出 8 位数字返回 None。"""
    digits = re.sub(r"\D", "", str(date))
    return int(digits) if len(digits) == 8 else None


def local_last_stamp():
    """本地 vipdoc 日线里已存在的最后一个交易日 -> int(YYYYMMDD)；读不到返回 None。

    盘前（当天K线尚未生成）时它就是上一交易日，用来多挂一条记录让排序指标立刻有值。
    """
    for path in (LDDAY, LDDAY_FALLBACK):
        try:
            with open(path, "rb") as f:
                size = os.fstat(f.fileno()).st_size
                if size < _LDDAY_REC:
                    continue
                f.seek(size - _LDDAY_REC)
                raw = f.read(_LDDAY_REC)
            return struct.unpack_from("<i", raw)[0]
        except (OSError, struct.error):
            continue
    print("警告: 读不到本地日线（%s），本轮只写口径日这一个日期戳" % LDDAY)
    return None


def load_snapshot(path, override_date):
    """读快照 -> (快照 dict, 口径日 YYYY-MM-DD)。"""
    with open(path, "r", encoding="utf-8") as f:
        snap = json.load(f)
    if override_date:
        return snap, override_date
    date = str(snap.get("date") or "").strip()
    if not date:
        date = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")
        print("警告: 快照内没有 date 字段，口径日回退为文件修改日期 %s" % date)
    return snap, date


def freshness(snap):
    """快照抓取时刻 -> (原文, 距今分钟数|None)。"""
    raw = str(snap.get("fetched_at") or "").strip()
    try:
        got = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw or "未知", None
    return raw, (datetime.now() - got).total_seconds() / 60.0


def ensure_datanos():
    """确保各计分平台的数据号已在 datacfg.dat 里注册（属性=数值序列），缺失则追加。

    通达信这条表是定长 60 字节记录；追加前先备份一次 datacfg.dat（只在 .bak 不存在时备份，
    保住原始副本）。文件缺失或结构异常时只告警不改动 —— 数据落地失败不该拖垮整条管线。
    数据号 4/5/6 已弃用、不再写入，故只补 PLATFORM_SIGS 里仍存在的号。
    """
    with open(DATACFG, "rb") as f:
        raw = f.read()
    if not raw or len(raw) % _DATACFG_REC:
        print("警告: %s 不存在或长度不是 %d 的整数倍，跳过数据号注册（请在 .901 手工新增 %s）"
              % (DATACFG, _DATACFG_REC,
                 "/".join("%d" % no for _p, no, _n in PLATFORM_SIGS)))
        return
    have = {}
    for off in range(0, len(raw), _DATACFG_REC):
        have[struct.unpack_from("<i", raw, off)[0]] = off
    missing = [(p, no, nm) for p, no, nm in PLATFORM_SIGS if no not in have]
    if not missing:
        return

    backup = DATACFG + ".bak"
    if not os.path.exists(backup):
        try:
            with open(backup, "wb") as f:
                f.write(raw)
            print("已备份原始数据号表 -> %s" % backup)
        except OSError as e:
            print("警告: 备份 %s 失败（%s），为安全起见跳过注册" % (DATACFG, e))
            return

    tail = raw[len(raw) - 4:len(raw)]        # 沿用末条记录的尾字段，避免自造未知值
    add = b""
    for platform, no, name in missing:
        nm = name.encode("gb18030")[:32].ljust(32, b"\0")
        add += struct.pack("<ii", no, 1) + nm + b"\0" * 16 + tail
    try:
        with open(DATACFG, "ab") as f:
            f.write(add)
    except OSError as e:
        print("警告: 写入 %s 失败（%s），跳过数据号注册" % (DATACFG, e))
        return
    print("已注册数据号 %s（%s），通达信需重启后 .901 才会列出"
          % ("、".join("%d=%s(%s)" % (no, name, platform) for platform, no, name in missing),
             DATACFG))


def score_all(snap):
    """快照 -> 打分清单 [{code, market, name, cover, rank_score, score, plat_scores}]，按分值降序。

    cover / rank_score 直接取 ``hot.score_parts``（加权平台数 + 含韭研红股固定分的名次分），
    与因子面板口径一字不差；本脚本只把权重由 420 换成 1000。
    plat_scores 取 ``hot.platform_scores``（逐平台名次分贡献，五列相加 = rank_score）。
    """
    items = []
    for inst, rec in hot.collect_best_ranks(snap).items():
        code, _, mkt = inst.partition(".")
        cover, rank_score = hot.score_parts(rec)
        items.append({"code": code, "market": _MKT_NO.get(mkt, 0), "name": rec.get("name", ""),
                      "cover": cover, "rank_score": rank_score,
                      "plat_scores": hot.platform_scores(rec),
                      "score": cover * COVER_WEIGHT + rank_score})
    items.sort(key=lambda it: (-it["score"], it["code"]))
    return items


def _write_dir(sig_no, values, stamps):
    """整份重写 signals_user_<sig_no>\\<市场>_<代码>.dat，并清理掉出榜单的残留旧文件。

    ``values`` = {文件名: 分值}；``stamps`` = 日期戳列表（升序，每票逐条写入，正常两条：
    口径日 + 本地日线最后交易日，见模块头「日期戳 / 盘前可见」）。返回 (写入数, 失败数, 清理数)。
    """
    sig_dir = SIG_DIR_FMT % sig_no
    try:
        os.makedirs(sig_dir, exist_ok=True)
    except OSError as e:
        print("警告: 无法创建 %s（%s），跳过数据号 %d" % (sig_dir, e, sig_no))
        return 0, 0, 0
    ok = lost = 0
    for name, val in values.items():
        try:
            with open(os.path.join(sig_dir, name), "wb") as f:
                for s in stamps:
                    f.write(struct.pack("<if", s, float(val)))
            ok += 1
        except OSError as e:      # 通达信偶尔占用文件，下个 10 分钟周期会补上
            print("警告: 写入 %s 失败（%s）" % (name, e))
            lost += 1

    stale = 0
    try:
        names = os.listdir(sig_dir)
    except OSError:
        names = []
    for name in names:
        if _DAT_RE.match(name) and name not in values:   # 掉出榜单的残留旧分值
            try:
                os.remove(os.path.join(sig_dir, name))
                stale += 1
            except OSError:
                pass
    return ok, lost, stale


def write_signals(items, stamps):
    """整份重写 .901 自定义数据：数据号 1 = 共振分，数据号 2/3/7/8/9 = 五个平台的名次分贡献。

    每只股票都写满这些通道（未上榜的平台显式写 0，避免通达信读到上一轮的旧值）。
    每个通道每票按 ``stamps`` 逐条写（口径日 + 本地日线最后交易日，见模块头「日期戳」）。
    数据号 4/5/6 已弃用、不再写入：每轮清空这些号的数据目录，
    免得通达信还读出上一版口径留下的旧分值（号段不重排）。
    """
    files = [("%d_%s.dat" % (it["market"], it["code"]), it) for it in items]
    tag = "/".join("%d" % s for s in stamps)

    ok, lost, stale = _write_dir(SIG_NO, {n: it["score"] for n, it in files}, stamps)
    print("自定义数据落地: 数据号 %d 共振分 写入 %d 只（失败 %d） 清理过期 %d 只 日期 %s -> %s"
          % (SIG_NO, ok, lost, stale, tag, SIG_DIR_FMT % SIG_NO))

    for platform, no, _name in PLATFORM_SIGS:
        values = {n: it["plat_scores"].get(platform, 0.0) for n, it in files}
        ok, lost, stale = _write_dir(no, values, stamps)
        print("自定义数据落地: 数据号 %d %s名次分 写入 %d 只（失败 %d） 清理过期 %d 只"
              % (no, platform, ok, lost, stale))

    for no in DEPRECATED_SIGS:          # 已剔除平台：整目录清空（values={} 即全部当残留删掉）
        _ok, _lost, stale = _write_dir(no, {}, stamps)
        print("自定义数据落地: 数据号 %d 已弃用（原平台已剔除） 清理历史残留 %d 只" % (no, stale))


def _blk_line(inst):
    """快照里的 instrument -> 通达信 .blk 行（市场位 + 6 位代码）；认不出返回 None。

    快照 sj88 的键是 ``SH600189`` 这种市场前缀写法，而 ``collect_best_ranks`` 给出的是
    ``600189.SH``，两种都兼容。
    """
    if "." in inst:
        code, _, mkt = inst.partition(".")
    else:
        mkt, code = inst[:2], inst[2:]
    no = _MKT_NO.get(mkt.upper())
    if no is None or len(code) != 6 or not code.isdigit():
        return None
    return "%d%s" % (no, code)


def _blk_day_start():
    """今天 00:00 的 Unix 时间戳，用来判断 55188.blk 是否已被「当日第一轮」写过。"""
    now = datetime.now()
    return datetime(now.year, now.month, now.day).timestamp()


def _blk_keys_existing():
    """读回 55188.blk 里已有的成分键（``市场位 + 6位代码``，7 字符）；读不到返回空集合。"""
    try:
        with open(BLK_SJ88, "rb") as f:
            raw = f.read()
    except OSError:
        return set()
    text = raw.decode("gbk", "ignore").replace("\r", "\n")
    return {ln for ln in text.split("\n") if len(ln) == 7 and ln.isdigit()}


def write_blk(items, snap):
    """落地通达信自选板块 ``blocknew\\55188.blk``：55188 三榜（主力/人气/龙头）并集，按共振分降序。

    文件格式（实测其余 .blk 样本一致）：开头一个 CRLF，随后每只股票一行 ``CRLF + 市场位 + 6位代码``
    （市场位 1=沪 0=深 2=北，与 ``_MKT_NO`` / .dat 文件名前缀同一约定）；无表头、无注释。
    写法（用户口径「当日先清空一次、其后只追加新增」）：**当日第一轮整份重写**（= 清空一次、落当日基准），
    其后各轮先读回文件已有成分、只把**当前并集里尚未出现**的代码追加到末尾 —— 新上榜自动加入、
    掉榜的仍留在板块里，且同一只股票一天只落一行（不会像「整份追加」那样每 10 分钟重复一遍）。
    「当日第一轮」按目标文件的 mtime 判断：mtime 不在今天即今天还没写过 -> 清空重写，否则追加；
    文件不存在/读不到也按清空重写处理。故不需要额外的状态文件，且程序二往同一文件追加的内容
    不会被本脚本的后续轮次抹掉（明天 00:00 那轮才会再清一次）。
    以二进制写入以免文本模式把 ``\\n`` 二次翻译成 CRLF。写入失败只告警、不拖垮管线。返回写入只数。
    """
    score_of = {"%d%s" % (it["market"], it["code"]): it["score"] for it in items}
    keys = set()
    for board in SJ88_BOARDS:
        for inst in ((snap.get("sj88") or {}).get(board) or {}):
            line = _blk_line(inst)
            if line:
                keys.add(line)
    ordered = sorted(keys, key=lambda k: (-score_of.get(k, 0.0), k))
    try:
        first = os.path.getmtime(BLK_SJ88) < _blk_day_start()
    except OSError:
        first = True                  # 文件不存在/读不到 -> 当今天第一轮处理
    if first:
        todo, mode, note = ordered, "wb", "当日首轮整份重写"
    else:
        have = _blk_keys_existing()
        todo = [k for k in ordered if k not in have]
        mode, note = "ab", "追加新增"
    if not todo:
        print("自选板块落地: 55188.blk 无新增（三榜并集 %d 只已全在板块内） -> %s"
              % (len(ordered), BLK_SJ88))
        return 0
    try:
        with open(BLK_SJ88, mode) as f:
            f.write("".join("\r\n" + k for k in todo).encode("gbk"))
    except OSError as e:            # 通达信偶尔占用该文件，下个 10 分钟周期会再写一次
        print("警告: 写入 %s 失败（%s）" % (BLK_SJ88, e))
        return 0
    print("自选板块落地: 55188.blk %s %d 只（55188 主力/人气/龙头 三榜并集共 %d 只，按共振分降序） -> %s"
          % (note, len(todo), len(ordered), BLK_SJ88))
    return len(todo)


def build_formula(items, date, stamp, snap):
    """拼通达信排序公式源码。"""
    fetched, mins = freshness(snap)
    if mins is None:
        status = "未知（快照内 fetched_at 缺失）"
    elif mins > 30:
        status = ("快照已停更 %.0f 分钟 —— 指标不会变化，请检查 a_fetch_hot_snapshot.py 是否在跑"
                  % mins)
    else:
        status = "新鲜（%.0f 分钟前抓取）" % mins

    L = []
    L.append("{=================================================================")
    L.append(" 五平台人气共振 · 历史行情指标排序")
    L.append(" ---------------------------------------------------------------")
    L.append(" 数据来源 : last_good.json（东方财富/淘股吧/开盘啦/55188/韭研公社 各榜前 20）")
    L.append(" 口径日   : %s（数据戳 %d）" % (date, stamp))
    L.append(" 抓取时刻 : %s" % fetched)
    L.append(" 时效状态 : %s" % status)
    L.append(" 覆盖个股 : %d 只（加权覆盖 >= 2 的 %d 只 + 其余 %d 只；55188 记 2.0、其余记 1.0）"
             % (len(items), sum(1 for i in items if i["cover"] >= 2),
                sum(1 for i in items if i["cover"] < 2)))
    L.append("")
    L.append(" 打分规则 : 共振分 = 加权覆盖平台数 x 1000 + 累加((21 - 该榜单名次) x 平台名次分权重) + 韭研红股 120")
    L.append("            加权覆盖平台数 = 上榜平台去重后按平台权重求和（55188 记 2.0，其余记 1.0，")
    L.append("            理论满配 6.0；开盘啦·复盘、55188 主力/人气/龙头各榜得分相加，但仍只算 1 个平台；")
    L.append("            名次分权重：55188 主力/人气/龙头 三榜各 x3（单榜上限 60，三榜合计上限 180），")
    L.append("            东方财富/淘股吧/开盘啦 三家均 x1；")
    L.append("            韭研公社异动图红股无名次、算 1 个平台、另固定给 120 分）")
    L.append("            平台数越多、名次越前得分越高；未上榜个股读出 0，自动排在最后")
    L.append("")
    L.append(" 平台列   : 东方财富 / 淘股吧 / 开盘啦 / SJ88(55188) / 韭研公社 五列")
    L.append("            各列 = 该平台的**名次分贡献**（该平台各榜 max(0, 21 - 名次) x 该平台名次分权重之和，")
    L.append("            开盘啦只取「复盘人气榜」、55188 主力/人气/龙头各榜得分均相加进本平台列）")
    L.append("            五列相加 = 共振分里的名次分部分；韭研公社红股无名次，固定 120 记在韭研公社列")
    L.append("")
    L.append(" 派生列   : 开盘涨跌幅 / 明日涨跌幅 / 昨日振幅 / 昨换(昨日换手率) / 昨几天 / 昨几板 / 昨连板")
    L.append("            （由原生 OHLC + 成交量/流通股本 + 涨停价算出，与 .901 自定义数据、与打分口径均无关；")
    L.append("            昨日振幅 / 昨换 / 昨* 三列取**上一根K线**的状态，即「昨日」）")
    L.append("")
    L.append(" 数据落地 : .901 自定义数据 · 数据号 %d（RQMAIN，数值序列）= 共振分；" % SIG_NO)
    L.append("            数据号 %s（数值序列）= 上表五个平台各自的名次分贡献，"
             % "/".join("%d" % no for _p, no, _n in PLATFORM_SIGS))
    L.append("            由 run_hot_rank_daily.bat 全天候每 10 分钟写入")
    L.append("            signals_user_<数据号>\\<市场>_<代码>.dat（市场: 1=沪 0=深 2=北）")
    L.append("")
    L.append(" 使用步骤 : 1) Ctrl+F 公式管理器 → 技术指标公式 → 其他类型 → 新建")
    L.append("            2) 公式名称填 %s，把本文件全部内容粘进源码框" % FNAME)
    L.append("            3) 点「测试公式」，通过后「确定」")
    L.append("            4) 输入 .401 进入「历史行情指标排序」")
    L.append("            5) 右键 →「更改排序指标」→ 选 %s → 按「共振分」降序" % FNAME)
    L.append("=================================================================}")
    L.append("")
    # 分值不逐股硬编码：榜单改由管线写进 .901 自定义数据，公式只留一行读取
    L.append("{---- 共振分读 .901 自定义数据（数据号 %d），换榜单无需改公式 ----}" % SIG_NO)
    L.append("RQ:=SIGNALS_USER(%d,%d);" % (SIG_NO, SIG_TYPE))
    L.append("")
    L.append("共振分:   RQ;")
    L.append("共振平台数: INTPART(RQ/1000);")
    L.append("")
    L.append("{---- 行情派生列：开盘涨跌幅 / 明日涨跌幅 / 昨日振幅 / 昨换"
             "（原生 OHLC + 成交量/流通股本 计算，与 .901 自定义数据无关）----}")
    L.append("开盘涨跌幅: (OPEN-REF(CLOSE,1))/REF(CLOSE,1)*100;")
    L.append("明日涨跌幅: (REFX(CLOSE,1)-CLOSE)/CLOSE*100;")
    L.append("昨日振幅: (REF(HIGH,1)-REF(LOW,1))/REF(CLOSE,2)*100;")
    L.append("昨换: REF(VOL,1)/CAPITAL*100;")
    L.append("")
    L.append("{---- 连板派生列：昨日几天几板 / 昨日连板（原生 OHLC + 涨停价计算，与 .901 自定义数据无关）----}")
    L.append("ZDF:=IF(CODELIKE('30') OR CODELIKE('68'),0.2,IF(CODELIKE('4') OR CODELIKE('8'),0.3,")
    L.append("     IF(NAMELIKE('ST'),0.05,0.1)));")
    L.append("ZT:=C>=ZTPRICE(REF(C,1),ZDF);")
    L.append("DB:=ZT=0 AND REF(ZT,1)=0;")
    L.append("QB:=ZT AND REF(ZT,1)=0 AND REF(DB,1);")
    L.append("TP:=BARSLAST(QB)+1;")
    L.append("PL:=COUNT(ZT,BARSLAST(QB)+1);")
    L.append("YX:=BARSLAST(DB)>BARSLAST(QB);")
    L.append("OKY:=REF(YX,1) AND REF(PL,1)>0;")
    L.append("昨几天: IF(OKY,REF(TP,1),0);")
    L.append("昨几板: IF(OKY,REF(PL,1),0);")
    L.append("昨连板: REF(BARSLASTCOUNT(ZT),1);")
    L.append("")
    L.append("{---- 各平台名次分贡献读 .901 自定义数据（数据号 %s），五列相加 = 共振分里的名次分部分 ----}"
             % "/".join("%d" % no for _p, no, _n in PLATFORM_SIGS))
    for platform, no, _name in PLATFORM_SIGS:
        L.append("%s: SIGNALS_USER(%d,%d);" % (PLATFORM_VAR[platform], no, SIG_TYPE))
    L.append("")
    L.append("{读取说明: 共振分与五列平台贡献都不是公式算出来的，而是管线每 10 分钟整份重写 %s\\"
             % (SIG_DIR_FMT % SIG_NO))
    L.append("<市场>_<代码>.dat（8 字节/条 = int32 日期 + float32 分值；每票通常两条 —— 口径日 + 本地日线")
    L.append(" 最后一个交易日，故盘前/当天K线出现前排序指标也有值，收盘后本地日线补上当日行情即自动回到单条）；")
    L.append(" 数据号 %d（共振分）与 %s（各平台名次分）需在 .901 里存在且属性为「数值序列」；"
             % (SIG_NO, "/".join("%d" % no for _p, no, _n in PLATFORM_SIGS)))
    L.append(" 数据号 %s 由 run_hot_rank_daily.bat 自动注册进 datacfg.dat（原表已备份为"
             % "/".join("%d" % no for _p, no, _n in PLATFORM_SIGS))
    L.append(" datacfg.dat.bak），首次注册后需重启通达信，.901 里才会列出；")
    L.append(" TYPE=%d 表示无数据周期返回 0。}" % SIG_TYPE)
    L.append("{信号说明: 共振平台数 = INTPART(共振分/1000)，即加权覆盖平台数**取整**（因其恒为整数，实际即原值）；")
    L.append(" 6 档 = 满配 6.0; 5 档 = 5.0; 4 档 = 4.0; 3 档 = 3.0; 2 档 = 2.0; 1 档 = 1.0; ")
    L.append(" 0 档 = 当日计分平台均未上榜。")
    L.append(" 五列平台值 = 该平台的名次分贡献，未上榜为 0；五列之和 = 共振分 - 共振平台数 x 1000。}")
    L.append("{注意    : 55188 以数字开头不能作通达信变量名，故列名缩写为 SJ88（即 55188 平台）；")
    L.append(" 开盘涨跌幅 = (开盘价 - 昨收) / 昨收 x 100（REF(CLOSE,1) = 昨收）；")
    L.append(" 明日涨跌幅 = (明日收盘 - 今收) / 今收 x 100，用未来函数 REFX(CLOSE,1) 引用次日收盘，")
    L.append(" 故最后一根K线（明日尚未发生）沿用上一根K线的引用值，属正常现象、非计算错误；")
    L.append(" 昨日振幅 = **昨日**（上一根K线）的 (昨日最高 - 昨日最低) / 昨日的前一日收盘 x 100；")
    L.append(" 昨换 = **昨日**（上一根K线）的换手率 = 昨日成交量 / 流通股本 x 100（VOL=成交量、")
    L.append(" CAPITAL=流通股本，两者单位同为手，故比值 x 100 即百分数）；")
    L.append(" 这四列只由原生 OHLC + 成交量/流通股本 算出，与 .901 自定义数据、与打分口径均无关。")
    L.append(" 昨几天/昨几板/昨连板 = **昨日**（上一根K线）的涨停窗口状态：昨几天 = 从昨日所处这轮")
    L.append(" 涨停潮的首板起算的天数；昨几板 = 该窗口内的涨停次数（如 3 天 2 板）；昨连板 = 昨日往前")
    L.append(" 连续涨停的板数（断板即止）；昨日不在涨停窗口内则三列均为 0。")
    L.append(" 涨停比例按板块判定：创业/科创 20%、北交所 30%、ST 5%、其余 10%（与 lianban_scan.py 一致）；")
    L.append(" 这三列同样只由原生 OHLC + 涨停价算出，与 .901 自定义数据、与打分口径均无关。")
    L.append(" 数据号 4/5/6 已弃用（号段不重排、公式不再读取、管线也不再写入，每轮清空其残留 .dat）；")
    L.append(" 数据号 %d 与旧「五平台人气交叉」同通道，本链路接管后即为多平台口径；" % SIG_NO)
    L.append(" 旧 RENQI 公式无需改动、也会读出多平台分值。}")
    return L


def main():
    ap = argparse.ArgumentParser(description="五平台人气共振 -> 通达信历史行情指标排序（数据号 1 共振分 + 2/3/7/8/9 逐平台名次分）")
    ap.add_argument("--snapshot", default=JSON_PATH, help="快照路径（默认同目录 last_good.json）")
    ap.add_argument("--date", default=None, help="覆盖口径日 YYYY-MM-DD（默认取快照内 date）")
    args = ap.parse_args()

    if not os.path.exists(args.snapshot):
        print("错误: 快照不存在 %s" % args.snapshot)
        return 1
    snap, date = load_snapshot(args.snapshot, args.date)
    stamp = to_stamp(date)
    if stamp is None:
        print("错误: 口径日 %r 解析不出 8 位数字，未写入 .dat" % date)
        return 1

    items = score_all(snap)
    if not items:
        print("错误: 快照里没有任何榜单数据，未写入 .dat（保留上一轮分值）")
        return 1

    ensure_datanos()        # 数据号 2/3/7/8/9 缺则追加（先备份 datacfg.dat）
    # 口径日 + 本地日线最后交易日（盘前即上一交易日）：多挂一条让排序指标开市前就有值，
    # 收盘后本地日线补上当日行情时两者相同、自动 dedupe 回单条。
    stamps = sorted({s for s in (local_last_stamp(), stamp) if s})
    write_signals(items, stamps)
    write_blk(items, snap)

    L = build_formula(items, date, stamp, snap)
    with open(OUT, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(L) + "\n")

    print("股票数: %d  共振(加权覆盖 >= 2): %d"
          % (len(items), sum(1 for i in items if i["cover"] >= 2)))
    dist = {}
    for it in items:
        dist[it["cover"]] = dist.get(it["cover"], 0) + 1
    print("加权平台数分布: " + "  ".join("%.1f平台=%d" % (k, dist[k])
                                        for k in sorted(dist, reverse=True)))
    print("共振分区间: %.0f ~ %.0f" % (items[-1]["score"], items[0]["score"]))
    print("前 10 榜: " + " ".join("%s(%s,%.1f/%.0f)" % (i["code"], i["name"], i["cover"], i["score"])
                               for i in items[:10]))
    print("输出:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
