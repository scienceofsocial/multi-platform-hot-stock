# -*- coding: utf-8 -*-
"""多平台热门股票因子（五平台人气共振 · BigQuant AIStudio 适配版）。

因子定义
--------
    cover_platforms = 该股票当日上榜去重后的**加权平台数**
                      平台 ∈ {东方财富, 淘股吧, 开盘啦, 55188, 韭研公社}；
                      每个平台记 1，**55188 记 2.0**，
                      故理论满配 = 6.0（5 个平台 + 55188 额外 1.0）
    rank_score      = Σ_榜单 max(0, 21 - 该榜单名次) x 该榜所属平台的**名次分**权重
                      + 韭研公社红股固定 120 分
                      （名次范围 1~20；6 张真名次榜加权后上限 =
                        20(东方财富) + 20(淘股吧)
                        + 20(开盘啦·复盘)
                        + 60(55188·主力) + 60(55188·人气) + 60(55188·龙头) = 240，
                        加韭研红股 120 = 360；
                       55188 三榜名次分各 x3 记 60，东方财富 / 淘股吧 / 开盘啦 均为 x1）
    baidu_hit       = 1 若该股当日命中百度财经热搜「A股 · 今日」前 10，否则 0（**反向项**）
    factor          = 420 * (cover_platforms - baidu_hit) + rank_score

含义：**跨平台共振强度优先，同级内名次越靠前越高**。对记满 1 个平台的档位（东方财富、淘股吧、
开盘啦、韭研公社）而言，420 > 名次分上限 360，故多覆盖一个平台仍严格优于同级名次更好。
（历史：接入同花顺·指标平台后计分榜由 10 张变 11 张，名次分上限 200 -> 220，
旧的 200 权重已不满足该不等式 —— 7*200 + 220 = 1620 > 8*200 + 8 = 1608，故上调为 300；
接入韭研红股固定 60 分后上限再由 220 -> 280，故再上调为 320；
55188 三榜名次分各 x2、红股同步 60 -> 120 后上限再由 280 -> 370，故再上调为 400；
**剔除通达信平台**（cover 1.0 -> 2.0、
三榜名次分 x2 -> x3）后，计分榜由 11 张变 10 张、名次分上限 370 -> 410，故再上调为 420；
**同花顺只保留「热门股票」一张榜**（删去 1h/24h 热股）后，真名次榜由 10 张变 9 张、
名次分上限 410 -> 400，420 仍满足不等式、无需再调；
**剔除财联社 / 同花顺、并去掉开盘啦「盘中人气榜」**（财联社/同花顺快照仍抓取、仅留档；
盘中榜连抓取一并去掉）后，计分平台由 7 个变 5 个、真名次榜由 9 张变 6 张，
cover 满配 7.0 -> 6.0、名次分上限 400 -> 360，420 仍满足不等式、无需再调。）

**百度财经热搜是反向项**（详见数据说明 §9）：百度热搜衡量的是全网大众搜索热度，搜的人多
意味着散户注意力已被充分消耗，故对命中者**扣分**——命中前 10 则 ``cover_platforms`` 减 1
（下限 0、不取负），等价于**降一档共振级别**、固定 −420 分。百度热搜**不计入**
``cover_platforms``（不成为「第 8 个平台」）、**不产生 ``rank_score``**（虽有 1~10 名次，
但不走 ``21 - 名次`` 计分），也**不扩充候选池**（只上了百度热搜、没上任何计分平台榜的股票
不进明细表）。未命中（``baidu_rank`` 为空）与现有口径完全一致。

平台去重口径沿用原「人气交叉」的「共振级别」：同一平台的多个榜单只算 1 个平台。
其中**55188**的「主力排名」「人气热榜」「龙头」各是不同的榜，故各榜**各自计分并相加**
（55188 三榜各 x3、合计最高 180 分），但**仍各合并算 1 个平台**参与 cover_platforms 去重；
**55188 三榜**的名次分各 **x3**（``RANK_FACTOR``，单榜上限 20 -> 60）；
**东方财富 / 淘股吧 / 开盘啦** 三家的名次分口径完全一致（``RANK_FACTOR`` 均取缺省
1.0，三家均单榜计分：东财 1 榜、淘股吧取实时/24h 最好 1 次、开盘啦只取复盘 1 榜 = 20），
三家 **cover_platforms 均记 1.0**；
**55188 的 cover_platforms 记 2.0**；
淘股吧 实时/24h 保持原口径（取该平台内最好名次，只计 1 次）。
**韭研公社**的「异动图红股」是图片识别结果、**没有 1~20 名次**，故按「与 55188 三榜合计
同等」固定给 120 分（``JYGS_RED_SCORE``）、同时让 cover_platforms +1，明细表以 ``jygs_red``
列标记。对应共振级别：6 平台 = 满配、5 平台 = 顶级、3 = 三平台、2 = 双平台、1 = 独立热点。

因子方向约定 factor_direction = 1（因子值越大越看多），本因子天然正向（覆盖平台越多、
名次越靠前 → 值越大），**不取负号**（与股吧人气排名因子 factor = -guba_rank 不同）。

数据来源
--------
各平台人气榜前 20 名快照（通达信 / 同花顺 / 财联社仅留档、不参与打分）：

* 东方财富「人气榜」   -> JSON ``em``  : {代码: {rank, chg, name}}，chg = 较昨日名次变化
* 淘股吧「实时热搜」   -> JSON ``tgb.rt``  : {代码: {rank, name, today, week}}，today/7日 = 搜索次数
* 淘股吧「24h热搜」    -> JSON ``tgb.h24`` : 同上
* 同花顺「热门股票」   -> JSON ``ths_poi`` : {代码: {rank, name}}，服务端渲染 HTML 的左侧导航
                        顺序即名次（**已剔除权重**：仅由快照留档，不参与 cover_platforms /
                        rank_score / 候选池；抓取侧照旧，下游全部忽略）
* 财联社「热榜」       -> JSON ``cls`` : {代码: {rank, chg, name}}，chg = 涨跌幅(%)
                        （**已剔除权重**：仅由快照留档，不参与 cover_platforms / rank_score /
                        候选池；抓取侧照旧，下游全部忽略）
* 通达信「人气榜」     -> JSON ``tdx`` : {代码: {rank, hot, chg, name}}，hot = 人气值
                        （**已剔除权重**：仅由快照留档，不参与 cover_platforms / rank_score /
                        候选池；抓取侧照旧，下游全部忽略）
* 开盘啦「复盘人气榜」 -> JSON ``kph.fp`` : {代码: {rank, chg, zf, name}}，chg = 名次变化，zf = 涨幅(%)
                        （原「盘中人气榜」``kph.pz`` 已随抓取侧一并去掉，快照不再产出）
* 55188「主力排名」    -> JSON ``sj88.zl`` : {代码: {rank, name, main_force_pct}}，沪深A股前 10
* 55188「人气热榜」    -> JSON ``sj88.rb`` : {代码: {rank, name}}，前 10
* 55188「龙头」        -> JSON ``sj88.ld`` : {代码: {rank, name}}，精选板块行徽标「龙一」~「龙十」
                        （板块合并，同一只股票上榜多个板块时取其最好名次，前 10；
                        板块内带「龙N」徽标的龙头**不足 4 只**的板块整块丢弃，见快照侧 ``SJ88_MIN_LEADERS``）
* 韭研公社「异动图红股」 -> JSON ``jygs`` : {代码: 名称}，**异动图图片识别结果、没有名次**

这些页面（人气交叉.html）被 base64 + XOR 保护，故本脚本不自己抓取，只消费目录内已落盘的快照
``last_good.json``；该快照由同目录的抓取脚本 ``a_fetch_hot_snapshot.py`` 直接请求各平台接口生成
（含仅留档的通达信人气榜；不再依赖 三平台人气交叉.exe；韭研红股由 ``a_fetch_jygs_red.py`` 按口径日缓存提供）。
口径日优先取快照内嵌的 ``date`` 字段，取不到才回退快照文件的修改日期，所以正常流程下无需显式 --date。

数据流
------
    last_good.json 快照（计分 5 平台前 20 + 通达信/同花顺/财联社留档）
      -> 4+ 列明细 [date, instrument, name, em_rank, tgb_rank,
                   kph_fp_rank, sj88_zl_rank, sj88_rb_rank, sj88_ld_rank,
                   jygs_red, baidu_rank, cover_platforms, rank_score] 增量追加
                   a_duopingtai_hot_factor.csv
      -> 重复日期数据检查：同一 (date, instrument) 只保留一行，发现重复行即删除该行
      -> 因子面板 [date, instrument, factor]
         （factor = 420 * (cover_platforms - baidu_hit) + rank_score）
      -> AIStudio 端：dai.DataSource.write_bdb 落成平台数据源 alpha_duopingtai_hot_factor_data，
         并按 factors.submit_factor 提交因子（元数据 + 口径参数）

说明：本脚本**不做本地因子回测/分析**（IC/IR、分层、绩效一律不在本地算），因子分析由
AIStudio 平台的因子分析流程（AlphaMiner）基于上面的数据源完成；提交时只带因子口径参数
（group_num / instruments / benchmark / data_process / factor_direction）。

用法
----
    python a_duopingtai_hot_factor.py                     # 读快照 + 增量落 CSV + 落库 + 提交
    python a_duopingtai_hot_factor.py --date 2026-09-14   # 显式指定口径日（覆盖推导值）
    python a_duopingtai_hot_factor.py --snapshot last_good.json   # 指定快照文件
    python a_duopingtai_hot_factor.py --from-csv          # 不读快照，直接用已落盘 CSV 做落库/提交
    python a_duopingtai_hot_factor.py --no-submit         # 只落 CSV 不落库不提交
    python a_duopingtai_hot_factor.py --check-dup         # 只做重复日期数据检查（不读快照）

定时
----
本脚本不自带抓取，依赖同目录 ``a_fetch_hot_snapshot.py`` 产出的快照，因此**必须在快照刷新后运行**，
推荐用 Windows 计划任务把两者串起来：先跑 a_fetch_hot_snapshot.py，5 分钟后跑本脚本。
非交易日/快照未更新时，脚本按 (date, instrument) 去重后「增量 0 行」，不会产生脏数据。
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

#: 本机 pyarrow 13.0.0 是用 NumPy 1.x 编译的，在 NumPy 2.x 下 import 时会在 stderr 打出
#: 一大段 "AttributeError: _ARRAY_API not found" 回溯。pandas 只是探测性地尝试加载 pyarrow
#: （可选加速），失败会正常回退，功能不受影响，但会污染 .bat 日志。这里在 import pandas 前
#: 把 pyarrow 标记为不可用，让 pandas 直接走「未安装 pyarrow」分支，日志保持干净。
#: 不要试图升级全局 pyarrow：bigquant-core 硬约束 pyarrow<14.0.0，而 numpy 2.x 被百余个
#: 已编译包依赖，两端都动不了。
sys.modules.setdefault("pyarrow", None)

import pandas as pd

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hot_trace as trace                      # noqa: E402  「变化即追加」落盘工具

# ------------------------------ 常量 ------------------------------

#: 所有输入/输出都在本脚本所在目录，随目录整体搬迁无需改路径
_DIR = os.path.dirname(os.path.abspath(__file__))
#: 快照文件（8 平台人气榜原始数据；可用 --snapshot 覆盖）
JSON_NAME = "last_good.json"
JSON_PATH = os.path.join(_DIR, JSON_NAME)
#: 明细 CSV（ASCII 前缀 a_：中文名在上传链路会被截断/编码损坏）
CSV_NAME = "a_duopingtai_hot_factor.csv"
CSV_PATH = os.path.join(_DIR, CSV_NAME)
#: 明细「变化轨迹」JSONL（追加、永不覆盖）；与快照/日报两份 trace 同放 _hot_archive
TRACE_NAME = "factor_trace.jsonl"
TRACE_PATH = os.path.join(trace.TRACE_DIR, TRACE_NAME)

#: 明细表列（一行 = 一只股票在一个口径日的各榜单名次；开盘啦·复盘、55188 主力/人气/龙头
#: 各自成列；jygs_red = 是否韭研公社异动图红股（1/0，
#: 红股无名次、但贡献 cover_platforms +1 与固定 rank_score）；
#: baidu_rank = 百度财经热搜「A股 · 今日」前 10 的**反向**名次 1~10，未命中为空
#: （只影响 factor：命中则 cover_platforms 减 1；不进 cover_platforms / rank_score）；
#: cover_platforms = 加权平台数（55188 记 2.0，故可能不是整数）
#: 通达信 / 同花顺 / 财联社已彻底剔除：快照 ``tdx`` / ``ths_poi`` / ``cls`` 仅留档，
#: 不进本表、不参与打分）
COLS = ["date", "instrument", "name",
        "em_rank", "tgb_rank",
        "kph_fp_rank", "sj88_zl_rank", "sj88_rb_rank", "sj88_ld_rank",
        "jygs_red", "baidu_rank", "cover_platforms", "rank_score"]

#: 基准平台 -> 该平台的榜单（55188 有多榜、得分相加；其余平台一榜一名次；
#: 韭研公社红股无名次，只让加权覆盖平台数 +1，另给固定名次分）
PLATFORM_BOARDS = {"东方财富": ("东方财富",), "淘股吧": ("淘股吧",),
                   "开盘啦": ("开盘啦·复盘",),
                   "55188": ("55188·主力", "55188·人气", "55188·龙头"),
                   "韭研公社": ("韭研公社",)}
#: 五个计分平台（通达信已剔除；财联社 / 同花顺已剔除，仅留档）
#: 与 a_fetch_hot_snapshot.py 的 PLATFORMS 相比少三个（tdx / ths_poi / cls）
PLATFORMS = list(PLATFORM_BOARDS)
#: 平台 **cover** 权重系数：**55188 记 2.0**，
#: 其余平台记 1.0。故理论满配 = 6.0（5 个平台 + 55188 额外 1.0）。
PLATFORM_FACTOR = {"55188": 2.0}
#: 平台 **名次分** 权重系数：**55188 三榜名次分各 x3**（单榜上限 20 -> 60，三榜合计上限 180）；
#: 其余平台记 1.0（东方财富 / 淘股吧 / 开盘啦 三家名次分口径完全一致，均取缺省 1.0）。
RANK_FACTOR = {"55188": 3.0}
#: 榜单 -> 所属基准平台（多榜平台如「55188·主力」归「55188」，用于取该平台系数）
BOARD_PLATFORM = {board: platform for platform, boards in PLATFORM_BOARDS.items()
                  for board in boards}
#: 榜单 -> 明细表里该榜单名次的列名（一一对应，开盘啦·复盘/55188 各榜各占一列）
#: 韭研公社红股没有名次，故不在此表内（只算平台数，另以 jygs_red 列标记）
PLATFORM_FIELD = {"东方财富": "em_rank", "淘股吧": "tgb_rank",
                  "开盘啦·复盘": "kph_fp_rank",
                  "55188·主力": "sj88_zl_rank", "55188·人气": "sj88_rb_rank",
                  "55188·龙头": "sj88_ld_rank"}

#: 韭研公社红股：榜单键 + 占位值（只登记「上榜」事实；分值见 JYGS_RED_SCORE）
JYGS_BOARD = "韭研公社"
JYGS_PRESENCE = 0
#: 韭研公社红股固定名次分：无名次，按「与 55188 三榜同等」固定给 120 分（同时 cover +1）
JYGS_RED_SCORE = 120

#: 百度财经热搜「A股 · 今日」前 10：**反向项**（命中扣分）。它不是第八个平台，
#: 不进 cover_platforms / rank_score，也不扩充候选池，只把名次落到 baidu_rank 列。
BAIDU_BOARD = "百度热搜"
BAIDU_TOP_N = 10

#: 榜单名次上限（各榜均取前 20，清洗口径同 clean_renqi.py：1 <= rank <= 20）
MAX_RANK = 20
#: rank_score 的基数：单个榜单名次得分 = max(0, RANK_BASE - rank)
RANK_BASE = MAX_RANK + 1
#: 覆盖平台数的权重（因子面板口径）。对记满 1 个平台的档位（东方财富、淘股吧、开盘啦、
#: 韭研公社）而言，420 > 名次分上限 360，故多覆盖一个平台仍严格优于同级名次更好。
#: （历史：接入同花顺·指标平台后名次分上限 200 -> 220，故 200 上调为 300；
#: 接入韭研红股固定 60 分后上限再由 220 -> 280，故再上调为 320；
#: 55188 三榜名次分各 x2、韭研红股同步 60 -> 120 后上限再由 280 -> 370，故再上调为 400；
#: 剔除通达信（cover 1.0 -> 2.0、三榜 x2 -> x3）后上限 370 -> 410，
#: 故再上调为 420；同花顺只保留「热门股票」一榜后上限 410 -> 400，420 仍满足、不再上调；
#: **剔除财联社 / 同花顺、并去掉开盘啦「盘中人气榜」**后计分平台 7 -> 5、真名次榜 9 -> 6，
#: 名次分上限 400 -> 360，420 仍满足、不再上调。）
COVER_WEIGHT = 420

#: 因子 id / 名称（AIStudio 全局唯一，小写字母/数字/下划线，以字母开头）
FACTOR_ID = "alpha_duopingtai_hot_factor"
FACTOR_NAME = "多平台热门股票因子"
FACTOR_DATASOURCE_ID = "alpha_duopingtai_hot_factor_data"
FACTOR_DATASOURCE_COLUMN = "factor"
#: 空串 = 默认主站空间（「我的因子」）
FACTOR_SPACE_ID = ""

FACTOR_SQL = """-- 多平台热门股票因子：factor = 420 * (cover_platforms - baidu_hit) + rank_score
--   cover_platforms = 当日上榜的**加权平台数**（非整数）
--                     （东方财富/淘股吧/开盘啦/55188/韭研公社；
--                      55188 记 2.0，其余记 1.0，故理论满配 = 6.0）
--   baidu_hit       = 1 若命中百度财经热搜「A股 · 今日」前 10（**反向项**），否则 0；
--                     (cover_platforms - baidu_hit) 下限 0、不取负（等价于降一档共振级别）
--   rank_score      = Σ_榜单 max(0, 21 - 该榜单名次) x 该榜所属平台名次分权重 + 韭研红股固定 120 分
--                     名次 1~20；6 张计分榜加权后上限 = 20+20+20+60+60+60 = 240，
--                     加韭研红股 120 合计上限 360（55188 三榜名次分各 x3 记 60，
--                     东方财富/淘股吧/开盘啦三家均 x1）。
--                     普通平台单榜；开盘啦只取复盘 1 榜（20）；55188 主力/人气/龙头
--                     三榜各自计分相加（各 x3，合计 180）
--                     韭研公社红股无名次，cover +1、rank_score 固定 120；
--                     百度热搜不计入 cover_platforms、不产生 rank_score，只做上述反向扣分
-- 【口径说明】原始数据来自五个计分平台人气榜/热搜榜前 20 名快照（通达信/同花顺/财联社榜
-- 仅由快照留档、不带任何权重）+ 百度财经热搜前 10（页面加密、
-- 盘中动态刷新，平台内无对应原始表），故本 SQL 以数据源 alpha_duopingtai_hot_factor_data（列
-- factor）为输入，声明其可复算口径：同一 (date, instrument) 唯一，date 为榜单口径日；
-- 平台去重（55188 主力/人气/龙头各榜得分相加但仍只算
-- 1 个平台；淘股吧实时/24h 同平台取最好名次），
-- 55188 三榜名次分各 x3（cover 记 2.0），
-- 命中百度热搜前 10 的反向扣 1 档平台数，
-- factor 越大 = 跨平台共振越强且名次越靠前
-- （因子方向为正，factor_direction = 1，不取负号）。
SELECT date, instrument, factor
FROM alpha_duopingtai_hot_factor_data
WHERE date <= '{end_date}'
  AND factor IS NOT NULL;
"""


# ------------------------------ 工具 ------------------------------

def to_instrument(code):
    """平台代码 -> instrument（带 .SH / .SZ / .BJ 后缀）。

    接受 ``SH601091`` / ``601091.SH`` / ``601091`` 三种写法：
    带交易所前缀的直接搬成后缀；不带前缀的按号段推断（4/8 开头 -> 北交所，
    6/9 开头 -> 沪市，其余 -> 深市）。
    """
    s = str(code).strip().upper()
    for mkt in ("SH", "SZ", "BJ"):
        if s.startswith(mkt):
            return s[len(mkt):].zfill(6) + "." + mkt
        if s.endswith("." + mkt):
            return s[: -len(mkt) - 1].zfill(6) + "." + mkt
    num = s.zfill(6)
    if num.startswith(("4", "8")):          # 北交所 43/83/87/92
        return num + ".BJ"
    if num.startswith(("6", "9")):          # 沪市 60/68/90
        return num + ".SH"
    return num + ".SZ"                       # 深市 00/30/20/15


def to_rank(value):
    """名次 -> 1~MAX_RANK 的整数；非法/越界（含空值）返回 None。"""
    if value is None:
        return None
    try:
        r = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return r if 1 <= r <= MAX_RANK else None


def snapshot_date(snapshot, json_path, override):
    """口径日推导：--date 优先；其次快照内嵌日期字段；最后退快照文件修改日期。"""
    if override:
        return pd.to_datetime(override).strftime("%Y-%m-%d")
    if isinstance(snapshot, dict):
        for key in ("date", "_date", "updated", "data_time", "update_time"):
            val = snapshot.get(key)
            if val:
                try:
                    return pd.to_datetime(val).strftime("%Y-%m-%d")
                except Exception:
                    continue
    mtime = datetime.fromtimestamp(os.path.getmtime(json_path)).strftime("%Y-%m-%d")
    print("  [注意] 快照内未找到日期字段，口径日回退为文件修改日期 %s；"
          "若该快照是历史快照，请用 --date 指定真实口径日" % mtime)
    return mtime


# ------------------------------ 解析 ------------------------------

def platform_scores(rec):
    """快照记录 -> {平台: 该平台的名次分贡献}（按 ``PLATFORMS`` 顺序，未上榜为 0.0）。

    单个平台的名次分 = Σ_该平台各榜 max(0, RANK_BASE - 名次) * RANK_FACTOR[该平台]
    （开盘啦·复盘、55188 主力/人气/龙头各榜得分相加）；
    韭研公社红股无名次，命中即固定 JYGS_RED_SCORE。

    Σ platform_scores().values() == rank_score，故各平台贡献之和可与共振分对账
    （共振分 = 加权覆盖平台数 * COVER_WEIGHT + Σ 平台贡献）。
    """
    out = {}
    for platform, boards in PLATFORM_BOARDS.items():
        s = 0.0
        for board in boards:
            if board not in PLATFORM_FIELD:    # 韭研公社红股无名次，下面单独给固定分
                continue
            r = rec.get(board)
            if r is None:
                continue
            s += max(0, RANK_BASE - r) * RANK_FACTOR.get(platform, 1.0)
        out[platform] = s
    if rec.get(JYGS_BOARD) is not None:
        out[JYGS_BOARD] = JYGS_RED_SCORE
    return out


def score_parts(rec):
    """快照记录 -> (cover_platforms, rank_score)。因子面板与通达信导出**共用**本函数。

    cover_platforms = Σ_平台 PLATFORM_FACTOR[平台]（该平台任一榜单上榜即计入，
                      多榜平台各榜得分相加但仍只算 1 个平台）
    rank_score      = Σ platform_scores()[平台]（逐平台名次分贡献之和，
                      含韭研红股固定 JYGS_RED_SCORE；无名次项）
    """
    cover = 0.0
    for platform, boards in PLATFORM_BOARDS.items():
        if any(rec.get(b) is not None for b in boards):
            cover += PLATFORM_FACTOR.get(platform, 1.0)
    rank_score = sum(platform_scores(rec).values())
    return cover, rank_score


def collect_best_ranks(snapshot):
    """快照 -> {instrument: {"name": 名称, 榜单: 该榜单名次}}。

    榜单键即 ``PLATFORM_FIELD`` 的键：开盘啦·复盘、55188 主力/人气/龙头
    各是不同的榜，各自独立成键（不取最小名次）；其余平台内的多榜单（淘股吧 实时/24h）
    仍取该平台最好（最小）名次。
    韭研公社红股无名次，以 ``JYGS_BOARD`` 键登记占位值 ``JYGS_PRESENCE``（让加权覆盖平台数
    +1，并固定贡献 ``JYGS_RED_SCORE`` 名次分，详见 ``score_parts``）。
    百度热搜是**反向榜**，只按 instrument 回填到**已在候选池里的行**（不扩充候选池），
    以 ``BAIDU_BOARD`` 键登记名次 1~10，不参与 cover_platforms / rank_score。
    """
    best = {}

    def put(code, board, rank, name=None):
        inst = to_instrument(code)
        rec = best.setdefault(inst, {})
        if name and not rec.get("name"):
            rec["name"] = str(name).strip()
        r = to_rank(rank)
        if r is None:
            return
        cur = rec.get(board)
        if cur is None or r < cur:
            rec[board] = r

    for code, val in (snapshot.get("em") or {}).items():
        put(code, "东方财富", (val or {}).get("rank"), (val or {}).get("name"))

    tgb = snapshot.get("tgb") or {}
    for board in ("rt", "h24"):
        for code, val in (tgb.get(board) or {}).items():
            put(code, "淘股吧", (val or {}).get("rank"), (val or {}).get("name"))

    # 同花顺「指标平台·热门股票」已彻底剔除（快照 ``ths_poi`` 仅留档、不带任何权重），
    # 故此处不再回填。

    # 财联社「热榜」已彻底剔除（快照 ``cls`` 仅留档、不带任何权重），故此处不再回填。

    # 通达信「人气榜」已彻底剔除（快照 ``tdx`` 仅留档、不带任何权重），故此处不再回填。

    kph = snapshot.get("kph") or {}
    for board, field in (("fp", "开盘啦·复盘"),):   # 仅复盘人气榜（盘中榜已去掉）
        for code, val in (kph.get(board) or {}).items():
            put(code, field, (val or {}).get("rank"), (val or {}).get("name"))

    sj88 = snapshot.get("sj88") or {}
    # 主力排名 / 人气热榜 / 龙头（板块合并，同股票取最好名次；龙头仅收「≥4 只龙头」的板块）
    for board, field in (("zl", "55188·主力"), ("rb", "55188·人气"), ("ld", "55188·龙头")):
        for code, val in (sj88.get(board) or {}).items():
            put(code, field, (val or {}).get("rank"), (val or {}).get("name"))

    # 韭研公社异动图红股：图片识别、**没有 1~20 名次**，故不走 put()，
    # 只登记「上榜」事实（cover_platforms +1、rank_score 由 score_parts 加固定的
    # JYGS_RED_SCORE）；值既支持「代码: 名称」也兼容「代码: {name: ...}」写法。
    for code, val in (snapshot.get("jygs") or {}).items():
        rec = best.setdefault(to_instrument(code), {})
        name = val.get("name") if isinstance(val, dict) else val
        if name and not rec.get("name"):
            rec["name"] = str(name).strip()
        rec[JYGS_BOARD] = JYGS_PRESENCE

    # 百度财经热搜（A股·今日前 10，反向榜）：只回填**已在候选池里的行**（不通 setdefault，
    # 否则「只上百度热搜、没上任何计分平台榜」的股票会被拉进明细表 = 扩充候选池）。
    for code, val in (snapshot.get("baidu") or {}).items():
        rec = best.get(to_instrument(code))
        if rec is None:
            continue
        r = to_rank((val or {}).get("rank"))
        if r is None or r > BAIDU_TOP_N:
            continue
        cur = rec.get(BAIDU_BOARD)
        if cur is None or r < cur:
            rec[BAIDU_BOARD] = r

    return best


def parse_snapshot(path, override_date=None):
    """读快照 -> 明细表 DataFrame（COLS 列，date 已落定）。"""
    if not os.path.exists(path):
        raise FileNotFoundError("快照文件不存在：%s" % path)
    with open(path, "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    data_date = snapshot_date(snapshot, path, override_date)

    rows = []
    for inst, rec in collect_best_ranks(snapshot).items():
        ranks = {PLATFORM_FIELD[b]: rec.get(b) for b in PLATFORM_FIELD}
        # cover_platforms / rank_score 共用 score_parts()：多榜平台各榜得分相加但仍只算 1 个
        # 平台；韭研红股无名次、cover +1 且固定 rank_score（详见 score_parts 与模块 docstring）
        cover_platforms, rank_score = score_parts(rec)
        rows.append(dict(
            date=data_date,
            instrument=inst,
            name=rec.get("name", ""),
            jygs_red=1 if rec.get(JYGS_BOARD) is not None else 0,
            baidu_rank=rec.get(BAIDU_BOARD),   # 百度热搜反向项：命中为 1~10，未命中为空
            cover_platforms=cover_platforms,
            rank_score=rank_score,
            **ranks,
        ))
    df = pd.DataFrame(rows, columns=COLS)
    if not df.empty:
        for col in PLATFORM_FIELD.values():     # 名次为整数（缺失保持空，不写 5.0）
            df[col] = df[col].astype("Int64")
        df["jygs_red"] = df["jygs_red"].astype("Int64")
        df["baidu_rank"] = pd.to_numeric(df["baidu_rank"], errors="coerce")   # float，缺失 = NaN
        df = df.sort_values(["cover_platforms", "rank_score"],
                            ascending=False).reset_index(drop=True)
    return df


# ------------------------------ 落盘 ------------------------------

def save_incremental(df, csv_path):
    """把明细写入 CSV，返回本次写入口径日的行数。

    同一口径日**以本次数据为准**：文件里该日的旧行先删除再整日写入，否则同一天会混排两种口径
    （例如升级新增平台列后，旧行仍缺新平台数据、「覆盖平台数」上限也比新行低一级）。
    其余口径日的旧行原样保留；其表头与当前列不一致时按新表头补齐，避免列错位。
    """
    if df.empty:
        return 0
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    if os.path.exists(csv_path):
        old = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
        if not old.empty and "date" in old.columns:
            old = old[~old["date"].astype(str).isin(set(out["date"]))]
        merged = pd.concat([old.reindex(columns=list(out.columns)), out.astype(object)],
                           ignore_index=True)
        merged.to_csv(csv_path, index=False, encoding="utf-8-sig")
        return len(out)
    out.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return len(out)


def _jsonable(value):
    """numpy/pandas 标量 -> 原生标量；缺失值 -> None（确保 JSONL 是严格 JSON）。"""
    if value is None or value is pd.NA:
        return None
    if hasattr(value, "item"):                      # numpy.int64 / float64 / bool_
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def append_detail_trace(df, trace_path=TRACE_PATH):
    """明细表「变化即追加」留档：该口径日的整日明细 -> factor_trace.jsonl。

    与 ``save_incremental`` 的覆盖写互补：CSV 只留当日终态，这里把**每次变化后的整日明细**
    追加进 JSONL，历史永不覆盖；内容与末行相同则跳过（不灌重复行）。
    返回 ``(是否追加, 说明文本)``。
    """
    if df.empty:
        return False, "明细为空，跳过轨迹追加"
    day = pd.to_datetime(df["date"].iloc[0]).strftime("%Y-%m-%d")
    records = [{col: _jsonable(row.get(col)) for col in COLS}
               for row in df.to_dict(orient="records")]
    fp = trace.fingerprint(records)
    record = {"key": day, "fingerprint": fp,
              "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "rows": len(records), "columns": list(COLS), "records": records}
    return trace.append_if_changed(trace_path, record, fp)


def clean_duplicate_dates(csv_path, keys=("date", "instrument")):
    """重复日期数据检查：同一 (date, instrument) 只保留一行，发现重复行即删除该行。

    返回 (删除行数, 剩余行数)；文件不存在时返回 (0, 0)。
    """
    if not os.path.exists(csv_path):
        print("  明细表不存在，无需检查：%s" % csv_path)
        return 0, 0
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if df.empty:
        return 0, 0
    before = len(df)
    df = df.drop_duplicates()                                   # 全列相同的重复行
    df = df.drop_duplicates(subset=list(keys), keep="first")    # 主键重复行
    removed = before - len(df)
    if removed:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print("  重复日期数据检查：删除 %d 行，剩余 %d 行" % (removed, len(df)))
    return removed, len(df)


def factor_series(df):
    """明细列 -> factor 值：``420 * (cover_platforms - baidu_hit) + rank_score``。

    ``cover_platforms`` 是**加权**平台数（55188 记 2.0，可为小数）、``rank_score``
    已含韭研红股固定分，二者均由 ``score_parts`` 落盘，故此处只做线性组合。
    ``baidu_hit`` = 1 若该行 baidu_rank 非空（命中百度财经热搜前 10），否则 0；
    明细/旧 CSV 若**没有** baidu_rank 列，视为未命中（历史口径不变，不会误扣）。
    ``(cover_platforms - baidu_hit)`` 下限 0、不取负（命中但只覆盖 1 个平台时不倒扣）。
    """
    cover = pd.to_numeric(df["cover_platforms"], errors="coerce")
    score = pd.to_numeric(df["rank_score"], errors="coerce")
    if "baidu_rank" in df.columns:
        hit = pd.to_numeric(df["baidu_rank"], errors="coerce").notna().astype("float64")
    else:
        hit = 0.0
    return (COVER_WEIGHT * (cover - hit).clip(lower=0) + score).astype("float64")


def load_panel_from_csv(csv_path):
    """复用已落盘明细 CSV：全部日期整体作为待提交因子面板。"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError("明细表不存在：%s（先跑一次不带 --from-csv 的取数）" % csv_path)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    for col in ("date", "instrument", "cover_platforms", "rank_score"):
        if col not in df.columns:
            raise ValueError("明细表缺少必需列 %s（应有 %s）" % (col, COLS))
    df["date"] = pd.to_datetime(df["date"])
    df["cover_platforms"] = pd.to_numeric(df["cover_platforms"], errors="coerce")
    df["rank_score"] = pd.to_numeric(df["rank_score"], errors="coerce")
    df = df.dropna(subset=["date", "instrument", "cover_platforms", "rank_score"]).copy()
    df["factor"] = factor_series(df)
    return df[["date", "instrument", "factor"]].reset_index(drop=True)


def build_panel(df):
    """明细表 -> 因子面板 [date, instrument, factor]。"""
    panel = pd.DataFrame({
        "date": pd.to_datetime(df["date"]),
        "instrument": df["instrument"].astype(str),
        "factor": factor_series(df),
    })
    return panel.dropna(subset=["date", "instrument", "factor"]).reset_index(drop=True)


# ------------------------------ 落库 / 提交 ------------------------------

def write_factor_datasource(panel):
    """把因子面板写入 DAI 数据源，返回 (datasource_id, datasource_column)；无 dai 返回 None。"""
    try:
        import dai
    except ImportError:
        print("  未检测到 dai SDK（当前非 AIStudio 环境），跳过因子数据源落库")
        return None
    data = panel[["date", "instrument", "factor"]].dropna(
        subset=["date", "instrument", "factor"]).copy()
    data["date"] = pd.to_datetime(data["date"])
    dai.DataSource.write_bdb(
        data=data,
        id=FACTOR_DATASOURCE_ID,          # 全局唯一，小写字母/数字/下划线，以字母开头
        unique_together=["date", "instrument"],
        indexes=["date"],
    )
    print("  因子数据源已落库：%s（%d 行）" % (FACTOR_DATASOURCE_ID, len(data)))
    return FACTOR_DATASOURCE_ID, FACTOR_DATASOURCE_COLUMN


def submit_factor(params, datasource=None):
    """提交因子（只带口径参数，不带本地绩效）；无 SDK 时只提示不报错。"""
    try:
        from bigalpha import factors
    except ImportError:
        print("  未检测到 bigalpha SDK（当前非 AIStudio 环境），跳过因子提交；"
              "本地结果见 %s" % CSV_NAME)
        return False
    datasource_id, datasource_column = datasource or (
        FACTOR_DATASOURCE_ID, FACTOR_DATASOURCE_COLUMN)
    factors.submit_factor(
        id=FACTOR_ID,
        performance_index=dict(params),
        performance_report="",
        metadata={},
        docs={"因子类型": "多平台人气共振/关注度因子",
              "口径": "factor = 420 * (cover_platforms - baidu_hit) + rank_score；"
                      "cover_platforms = 五平台（东方财富/淘股吧/开盘啦/55188/韭研公社；"
                      "通达信/同花顺/财联社已剔除、仅留档）"
                      "当日上榜的**加权平台数**（55188 记 2.0，其余 1.0，理论满配 6.0），"
                      "rank_score = Σ_榜单 max(0, 21 - 该榜单名次) x 该榜平台名次分权重 + 韭研红股固定 120，"
                      "名次范围 1~20（6 张计分榜加权后上限 240 + 红股 120 = 360；"
                      "55188 主力/人气/龙头三榜名次分各 x3、单榜上限 60，三榜合计 180；"
                      "东方财富/淘股吧/开盘啦 三家均 x1）；"
                      "baidu_hit = 1 若命中百度财经热搜「A股 · 今日」前 10（反向项）否则 0，"
                      "(cover_platforms - baidu_hit) 下限 0、不取负（命中即降一档共振级别）；"
                      "百度热搜不计入 cover_platforms、不产生 rank_score；"
                      "开盘啦「复盘人气榜」、55188"
                      "「主力排名」「人气热榜」「龙头」各自计分相加（开盘啦仅复盘 1 榜、最多 20 分；"
                      "55188 三榜各 x3、合计最多 180 分）"
                      "但合并只算 1 个平台，淘股吧 实时/24h 等同平台多榜单仍取最好名次计 1 次；"
                      "韭研公社异动图红股是图片识别结果、没有名次，让 cover_platforms +1、"
                      "并固定给 rank_score 120 分；"
                      "覆盖平台数越多、名次越靠前，因子值越大（factor_direction = 1，不取负号）"},
        name=FACTOR_NAME,
        desc="多平台人气榜前 20 名交叉共振强度。factor = 420 * (cover_platforms - baidu_hit) "
             "+ rank_score："
             "先按当日上榜的**加权平台数**（55188 记 2.0，其余记 1.0，"
             "理论满配 6.0；开盘啦·复盘、55188 主力/人气/龙头多榜不重复计数，"
             "韭研公社只计平台数）"
             "分层，再按各榜单名次（1~20，得分 = 21 - 名次，再乘该平台名次分权重；"
             "55188 主力/人气/龙头三榜名次分各 x3、单榜最多 60 分、三榜合计最多 180 分；"
             "东方财富/淘股吧/开盘啦三家均 x1；"
             "开盘啦仅「复盘人气榜」一榜、"
             "韭研红股固定 120 分）细分；"
             "通达信人气榜、同花顺指标平台、财联社热榜已剔除、不带任何权重（仅快照留档）；"
             "命中百度财经热搜前 10（baidu_hit = 1）的反向扣一档平台数（下限 0），"
             "百度热搜本身不计入平台数、不贡献名次分。"
             "值越大表示跨平台人气共振越强、名次越靠前（百度热搜命中者被反向下调），"
             "对应「顶级共振 / 三平台 / 双平台 / 独立热点」由强到弱。",
        factor_sql=FACTOR_SQL,
        datasource_id=datasource_id,
        datasource_column=datasource_column,
        space_id=FACTOR_SPACE_ID,
    )
    print("  因子已提交：%s（%s）" % (FACTOR_ID, FACTOR_NAME))
    return True


# ------------------------------ 主流程 ------------------------------

def run(args):
    params = {"group_num": args.group_num, "factor_field": "factor",
              "instruments": args.instruments, "factor_direction": 1,
              "benchmark": args.benchmark, "data_process": True}
    csv_path = args.out or CSV_PATH
    json_path = args.snapshot or JSON_PATH

    if args.check_dup:                      # 只做重复日期数据检查，不读快照
        clean_duplicate_dates(csv_path)
        return

    if args.from_csv:                       # 直接用已落盘的明细表做落库/提交
        clean_duplicate_dates(csv_path)
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        panel = load_panel_from_csv(csv_path)
    else:
        df = parse_snapshot(json_path, args.date)
        if df.empty:
            print("  快照内无有效榜单数据，退出：%s" % json_path)
            return
        print("  口径日 %s：%d 只股票（%s）"
              % (df["date"].iloc[0], len(df), os.path.basename(json_path)))
        # cover_platforms 是**加权**平台数（55188 记 2.0，其余记 1.0），故按实际取值
        # 分档统计，理论取值 1.0 ~ 6.0（5 个平台 + 55188 额外 1.0）
        print("  加权覆盖平台数分布（55188 记 2.0，满配 6.0）：")
        for val, cnt in (df["cover_platforms"].value_counts()
                         .sort_index(ascending=False).items()):
            print("    %-4s 平台：%d 只" % ("%.1f" % val, cnt))
        added = save_incremental(df, csv_path)
        print("  明细落盘：写入口径日 %d 行 -> %s" % (added, os.path.basename(csv_path)))
        clean_duplicate_dates(csv_path)
        _appended, trace_msg = append_detail_trace(df)
        print("  明细轨迹：%s" % trace_msg)
        panel = build_panel(df)

    if panel.empty:
        print("  因子面板为空，跳过落库/提交")
        return
    if args.no_submit:
        print("  --no-submit：只落 CSV，不落库不提交")
        return

    datasource = None
    try:
        datasource = write_factor_datasource(panel)
    except Exception as exc:
        print("  [提示] 因子数据源落库失败：%s" % exc)
    submit_factor(params, datasource)


def main():
    ap = argparse.ArgumentParser(
        description="多平台热门股票因子（五平台人气共振 · BigQuant AIStudio）")
    ap.add_argument("--date", default=None,
                    help="口径日 YYYY-MM-DD；缺省=快照内嵌日期，再缺省=快照文件修改日期")
    ap.add_argument("--snapshot", default=None, help="快照 JSON 路径；缺省 last_good.json")
    ap.add_argument("--out", default=None,
                    help="明细 CSV 路径；缺省 a_duopingtai_hot_factor.csv")
    ap.add_argument("--from-csv", action="store_true",
                    help="不读快照，直接用已落盘明细表做落库/提交")
    ap.add_argument("--check-dup", action="store_true", help="只做重复日期数据检查")
    ap.add_argument("--no-submit", action="store_true", help="只落 CSV，不落库不提交")
    ap.add_argument("--group-num", type=int, default=10, help="因子分析分层组数，默认 10")
    ap.add_argument("--instruments", default="全市场", help="股票池（提交参数）")
    ap.add_argument("--benchmark", default="中证500", help="基准（提交参数）")
    args = ap.parse_args()

    try:
        run(args)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print("[警告] 因子环节失败：%s" % exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
