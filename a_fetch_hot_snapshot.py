# -*- coding: utf-8 -*-
"""人气榜快照抓取（东方财富 / 淘股吧 / 开盘啦 / 55188 / 韭研公社 五个计分平台
   + 同花顺 / 财联社 / 通达信 三个仅留档平台）。

其中同花顺（``ths_poi``）/ 财联社（``cls``）/ 通达信（``tdx``）仅抓取留档、**不参与计分**
（相比照处理），故计分平台为**五个**。

同花顺平台只保留指标平台「热门股票」一张榜（``ths_poi``；原 1h/24h 热股已删）。

产出与 ``a_duopingtai_hot_factor.py`` 直接对接的快照文件（默认 ``last_good.json``）：

    {
      "date": "2026-09-18",                    # 榜单口径日，因子脚本直接读取
      "fetched_at": "2026-09-18 16:20:00",     # 抓取时刻（仅供排查）
      "em":  {"SH601091": {"rank": 1, "chg": 0, "name": "C沈鼓"}, ...},
      "tgb": {"rt":  {"SZ003026": {"rank": 2, "name": "中晶科技", "today": "79", "week": "67"}, ...},
              "h24": {"SZ002584": {"rank": 1, "name": "西陇科学", "today": "149", "week": "222"}, ...}},
      "ths_poi": {"SZ002614": {"rank": 1, "name": "奥佳华"}, ...},
      "cls": {"SH601091": {"rank": 1, "chg": 177.74, "name": "C沈鼓"}, ...},
      "tdx": {"SH600667": {"rank": 1, "hot": 8989569, "chg": "-0.53", "name": "太极实业"}, ...},
      "kph": {"fp": {"SZ000993": {"rank": 2, "chg": 2, "zf": 9.07, "name": "闽东电力"}, ...}},
      "sj88": {"zl": {"SH600293": {"rank": 1, "name": "三峡新材", "main_force_pct": 45.68}, ...},
               "rb": {"SH600664": {"rank": 1, "name": "哈药股份"}, ...},
               "ld": {"SZ300192": {"rank": 1, "name": "科德教育"}, ...},
               "ladder":  [{"board": 3, "count": 1, "stocks": [
                              {"instrument": "SZ002238", "name": "天威视讯",
                               "first_limit_up": 1790213436, "last_limit_up": 1790226636,
                               "plates": [{"name": "AI大模型/智能体", "reason": "..."}]}]}, ...],
               "sectors": {"大消费": {"limit_up_count": 7, "max_board": 4, "reason": "",
                                     "stocks": [{"instrument": "SZ002836", "name": "新宏泽",
                                                 "board": 1}, ...]}, ...},
               "leaders": {"大消费": [{"rank": 1, "instrument": "SZ002836", "name": "新宏泽",
                                       "lead": "龙一", "board": "4连板", "broken": false,
                                       "pct": 10.04, "amplitude": 10.96}, ...], ...}},
      "jygs": {"SH603636": "南威软件", ...},  # 韭研公社异动图红股（图片识别，没有名次）
      "baidu": {"SH601091": {"rank": 1, "rank_chg": 0, "name": "C沈鼓", "sector": "专用设备",
                            "chg": "-21.01%", "hot": "2120000"}, ...},
                                             # 百度财经热搜「A股 · 今日」前 10（**反向因子**：
                                             # 只供因子脚本扣分，不进 cover_platforms）
      "em_zt": {"SZ000498": {"name": "山东路桥", "fund": 59982095.0, "ltsz": 8188814951.35,
                             "seal_ratio": 0.007325, "board": 1, "sector": "基础建设"}, ...}
                                             # 东财「涨停池」全池（为 ① 龙头封单量提供
                                             # 封单金额 fund ÷ 流通市值 ltsz，仍未进 cover/rank_score）
    }

该结构完全对齐因子脚本的 ``collect_best_ranks()``：淘股吧 实时/24h 取该平台内最好名次
（只算 1 个平台）；开盘啦「复盘人气榜」、55188 主力排名/人气热榜/龙头
是各自独立的榜，得分相加（但仍各只算 1 个平台），故这里只需如实落盘各平台原始榜单。

``sj88`` 下的 ``ladder``（涨停梯队）/ ``sectors``（热门板块·带涨停家数）/ ``leaders``（板块龙头明细）
是 55188 ``overview`` 与 ``block_stocks`` 响应**原生附带的市场全景字段**，供「板块内涨停家数
（跟风小弟数量）≥3 判联动」「涨停封板时间节奏（早盘 10 点前批量封板 / 尾盘偷袭）」
「新老龙头交替（board/broken/pct/amplitude）」三条判据取数；顶层 ``em_zt``（东财涨停池）
则为「龙头封单 > 流通盘 5%」提供 ``seal_ratio``；
**这些字段与三张榜无关、不参与 cover_platforms / rank_score，下游因子脚本按 zl/rb/ld 取数、自动忽略**。

``ld`` 龙头榜与 ``leaders`` 明细共用**板块梯队门槛**（``SJ88_MIN_LEADERS``）：某板块内带
「龙N」徽标的行**不足 4 只** = 梯队不完整，该板块整体放弃（既不进 ``ld`` 榜、也不进 ``leaders`` 明细）。

五平台 + 三留档接口（同花顺/财联社/通达信仅抓取留档、不参与计分）
-----------------------------------------------------------------
* 东方财富「人气榜」  POST https://emappdata.eastmoney.com/stockrank/getAllCurrentList
                       body {"appId":"appId01","globalId":"786e4c21-70dc-435a-93bb-38",
                             "marketType":"","pageNo":1,"pageSize":100}
                       -> data[]: sc=代码(SH601091) / rk=名次 / rc / hisRc -> chg = hisRc - rc
                       接口不带股票名称，用腾讯行情 ``qt.gtimg.cn`` 补名并缓存
* 淘股吧「实时热搜 / 24h热搜」 GET https://www.tgb.cn/search/hotPop（HTML，需 Referer）
                       页面共 4 张 <table>：第 1、2 张为「个股」（实时 / 24h），第 3 张是用户、
                       第 4 张是主题；按表头「个股」筛出前两张，代码取 href=.../quotes/{sh|sz}\d{6}
* 同花顺「热门股票」   GET https://poi.10jqka.com.cn/default/index/index/channel/zyzb/from/frompos/
                       服务端渲染 HTML（无 xhr 接口），左侧导航每项形如
                       ``<a ... url="/optimal/index/default/code/002614/"><span>奥佳华</span></a>``，
                       按出现顺序取名次（1~top_n）-> ``ths_poi``；同花顺**仅此一张榜**
                       （原「1h热股 / 24h热股」接口已删）；**仅留档、不参与计分**
* 财联社「热榜」       GET https://api3.cls.cn/v1/hot_stock
                       ?app=cailianpress&os=android&sv=835&sign=md5(sha1("app=cailianpress
                       &os=android&sv=835"))  -> data[]: stock.StockID(sh601091) / .name /
                       .RiseRange(=涨跌幅)；名次 = 数组下标 + 1（接口给 30 条，只取前 20）；
                       **仅留档、不参与计分**
* 通达信「人气榜」     POST https://pul.tdx.com.cn/TQLEX?Entry=JNLPSE.hotStockList&RI=
                       body [{"listType":"0","cycle":"0"}]，Content-Type: text/plain;charset=UTF-8
                       响应是「表头行 + 数据行」的二维数组：market(1=沪/0=深) / sec_code /
                       stock_name / chg / ranking / totalCount(=人气值) / occur_time(=数据日)
* 开盘啦「复盘人气榜」 GET https://apphq.longhuvip.com/w1/api/index.php
                       ?Order=1&a=GetHotPHB&st=50&apiv=w28&Type=13&c=StockBidYiDong
                       （原「盘中人气榜」``Type=1&apiv=w21`` 已去掉，不再抓取）
                       需 UA ``lhb/5.9.3 (com.kaipanla.www; build:0; iOS 15.4.0) Alamofire/5.9.3``
                       -> {"Day":"2026-09-18","List":[[code, name, 涨幅%, 排名变化, 名次, 0, 0], ...]}
                       共 7 列、返回 50 条；代码不带市场前缀，按号段推断；名称接口自带
                       落盘为 ``kph.fp``
* 55188「主力排名」    GET https://www.55188.com/sec.php?action=overview（Accept: application/json）
                       -> main_force.all[]: code / name / rank / price / change_pct /
                       main_force_pct / sector（沪深A股 100 条，取前 top_n）；
                       顶层 trade_date 即榜单口径日、as_of 即快照时刻
  55188「人气热榜」    GET https://eq.10jqka.com.cn/open/api/hot_list/v1/hot_stock/a/hour/data.txt
                       （Referer: https://eq.10jqka.com.cn/）-> data.stock_list[]:
                       order / code / name / market(17=沪/33=深/151=北) / rate
                       ⚠ 该接口原与同花顺「1h热股」同源（实测 100 只代码完全一致），
                         同花顺 1h/24h 已删，故该数据源现只归 55188 人气热榜
                       主力排名/人气热榜/龙头三张榜各自独立落盘为 ``sj88.zl`` / ``sj88.rb`` / ``sj88.ld``
* 55188「龙头」        GET https://www.55188.com/sec.php?action=blocks&sort=1&order=1
                       -> rows[]: id / name / inc / strength / main_net（30 个精选板块）
                       GET ...sec.php?action=block_stocks&plate=<id>&order=1&st=<n>&index=0
                       -> rows[]: code / name / lead（行徽标「龙一」~「龙十」）/ ...
                       取每个板块默认「最正宗」视图前 10 行的 ``lead``
                       （同一只股票出现在多个板块时取其最好名次）-> ``sj88.ld``
                       需 Accept: application/json + X-Requested-With: XMLHttpRequest + Referer
* 韭研公社「异动图红股」 走同目录 ``a_fetch_jygs_red.py``（登录态 cookie -> Playwright 抓异动图
                       -> OpenCV 红墨比例 + OCR）；**红股没有 1~20 名次，只算 1 个平台、
                       rank_score 记 0**；识别结果按口径日缓存 ``jygs_red_cache.json``，
                       当日首次识别后每轮复用，失败沿用旧缓存，绝不阻塞其它平台
* 百度财经「热搜」     GET https://finance.pae.baidu.com/selfselect/listsugrecomm
                       ?tn=wisexmlnew&dsp=iphone&product=search&style=tablelist&market=ab
                       &type=day&day=YYYYMMDD&hour=15&pn=0&rn=&finClientType=pc
                       页面 ``finance.baidu.com/hotlist?mainTab=hotSearch&market=ab``
                       是前端渲染，直接抓该 XHR 接口：``market=ab`` 即 A 股、``type=day`` 即今日；
                       -> Result.list.body[]: code(6 位) / exchange(SH|SZ) / name / pxChangeRate
                       （已格式化涨跌幅 ``-21.01%``）/ heat（**原始热度值** ``2120000``，
                       页面显示的 ``210.1w`` 是二次格式化）/ blockName（行业）/ rankDiff（名次变化，
                       ``0`` 表示新进榜）；名次 = 数组下标 + 1，返回条数多于 10 故只取前 10
                       **该榜是反向因子**：只如实落盘，因子脚本据此对命中者扣分，不参与 cover 计数
* 东方财富「涨停池」   GET https://push2ex.eastmoney.com/getTopicZTPool
                       ?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt
                       &Pageindex=0&pagesize=300&sort=fbt:asc&date=YYYYMMDD&_=<ms>
                       -> data.pool[]: c(代码) / m(0深1沪) / n(名称) / p(价×100) / zdp(涨跌幅) /
                       amount(成交额) / **ltsz(流通市值·元)** / tshare(总股本) / hs(换手率) /
                       **lbc(连板数)** / fbt(首封时间 HHMMSS) / lbt(末封时间) / **fund(封单金额·元)** /
                       zbc(炸板次数) / **hybk(行业板块)** / zttj({days,ct})
                       **date 参数被真实尊重**（不同日期 -> 不同池、不同首只；``qdate`` 恒为最近
                       交易日、不作准；仅近 15 交易日可取）；落 ``em_zt`` 全池，并预算
                       ``seal_ratio = fund / ltsz`` 供「① 龙头封单 > 流通盘 5%」判据取数
                       **不参与 cover_platforms / rank_score**（东财计分仍只看 ``em`` 人气榜）

口径
----
* 各榜只保留 1 <= 名次 <= TOP_N(默认 20) 的记录（与 clean_renqi.py 一致）
* 不做任何「新股/ST」等额外过滤，榜单返回什么就落什么
* 同平台多榜单各自独立落盘，是否取最好名次/计分相加由因子脚本负责
* 百度热搜是**附加的反向榜单**（只取前 10）：它不进 cover_platforms、不计 rank_score，
  只供因子脚本对「命中前 10」的股票扣一档分，故不参与上述名次上限与平台去重口径

健壮性
------
* 单个平台抓取失败（网络/接口改版）时，**沿用上一次快照里该平台的数据**并告警，
  不会让整份快照变成空文件；全部平台都失败且无历史数据时才以退出码 1 结束
* 例外：**百度热搜失败时不沿用旧快照**（负向信号会过期，沿用会错扣分），
  直接落空榜 = 当日不扣分；其失败同样不阻塞其它平台
* 口径日优先取 ``--date``，其次取通达信 occur_time / 开盘啦 Day（即榜单实际数据日），
  最后才回退本机日期 —— 周末/节假日运行时不会错标成当天
* 名称缓存 ``names_cache.json`` 增量合并，只新增「代码 -> 名称」，不改动已有条目
* 快照按「先写临时文件再原子替换」落盘，写入中断不会损坏原文件

用法
----
    python a_fetch_hot_snapshot.py                  # 抓取并覆盖 last_good.json
    python a_fetch_hot_snapshot.py --loop           # 常驻，每 10 分钟抓一轮并播报新上榜
    python a_fetch_hot_snapshot.py --loop --interval 300    # 改间隔秒数（下限 30）
    python a_fetch_hot_snapshot.py --date 2026-09-18        # 显式指定口径日
    python a_fetch_hot_snapshot.py --out a_hot_0918.json    # 输出到别的文件
    python a_fetch_hot_snapshot.py --top 20 --timeout 30    # 调名次上限 / 超时
    python a_fetch_hot_snapshot.py --no-cache               # 平台失败时不回退历史快照

每轮抓完都会与「上一轮快照」比对，播报**本轮新进榜的股票**（上一轮各抓取平台都没上榜、
本轮进了任意一榜），并区分（百度为附加反向榜，不参与该播报）：

* ``[新出现]``                —— 当日第一次上榜
* ``[重回 · 首次 HH:MM:SS]``  —— 当日上过榜、掉出后又回来（首次时间点即上次出现时刻）

当日累计上榜的代码记在 ``hot_seen.json``，跨日自动清空。

定时
----
* 盘中盯盘：``--loop`` 常驻（按整 10 分钟对齐，不会逐轮漂移），Ctrl+C 退出
* 服务器常驻：Windows 计划任务每 10 分钟调一次裸命令（不带 --loop，即单轮）
  两者二选一即可，同时开只是重复抓取、互相覆盖 last_good.json
* 收盘出因子：交易日 15:05 后再跑 a_duopingtai_hot_factor.py，
  当日因子以最后一次快照为准
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime

import requests

try:
    #: 百度接口有 TLS 指纹风控，普通 requests 会被 403 ``hit risk``，须模拟浏览器指纹；
    #: 缺库时退化为 requests（百度榜随之抓不到，但按 §9.7 只落空榜、不影响其余平台）
    from curl_cffi import requests as curl_requests
except ImportError:                                # pragma: no cover - 环境缺库
    curl_requests = None

if hasattr(sys.stdout, "reconfigure"):
    # 常驻模式下进度要能实时看到（重定向到日志文件时也逐行刷出）
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# ------------------------------ 常量 ------------------------------

#: 输入/输出都在本脚本所在目录，随目录整体搬迁无需改路径
_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_NAME = "last_good.json"
OUT_PATH = os.path.join(_DIR, OUT_NAME)
NAMES_CACHE_NAME = "names_cache.json"
NAMES_CACHE_PATH = os.path.join(_DIR, NAMES_CACHE_NAME)
#: 当日「已出现股票」状态（首现时间），跨日自动清空
SEEN_NAME = "hot_seen.json"
SEEN_PATH = os.path.join(_DIR, SEEN_NAME)

#: 常驻循环间隔（秒）：默认 10 分钟；下限防止误填把接口打穿
LOOP_INTERVAL = 600
MIN_INTERVAL = 30

#: 各榜名次上限（清洗口径：1 <= rank <= TOP_N）
TOP_N = 20
#: 单请求超时（秒）
TIMEOUT = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# --- 东方财富 ---
EM_URL = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
EM_BODY = {"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38",
           "marketType": "", "pageNo": 1, "pageSize": 100}
EM_HEADERS = {"Content-Type": "application/json", "Referer": "https://guba.eastmoney.com/"}

# --- 淘股吧 ---
TGB_URL = "https://www.tgb.cn/search/hotPop"
TGB_HEADERS = {"Referer": "https://www.tgb.cn/"}
#: 淘股吧页面里 4 张表按表头区分：个股（实时/24h）、笔名（用户）、主题投资
TGB_BOARD_KEYS = ("rt", "h24")

# --- 同花顺（仅「指标平台·热门股票」一张榜；原 1h/24h 热股接口已删） ---
#: 同花顺「指标平台·热门股票」（服务端渲染 HTML，左侧导航的股票链接顺序即名次）
THS_POI_URL = "https://poi.10jqka.com.cn/default/index/index/channel/zyzb/from/frompos/"
THS_POI_HEADERS = {"Referer": "https://poi.10jqka.com.cn/"}
THS_POI_ITEM_RE = re.compile(
    r'url="/optimal/index/default/code/(\d{6})/"[^>]*>\s*<span[^>]*>([^<]{1,16})</span>')
#: 盘前占位假榜判据：该页返回的 20 只**全部落在同一个市场段**（代码前 5 位相同）。
#: 实测 2026-09-24「整榜同段」共 6 轮：08:52:53 / 08:53:54 / 09:00:09 / 09:07:42 / 09:10:07
#: 五轮全为 ``SZ000xxx``（太钢不锈 / 农产品 / 深纺织Ａ …，逐字不变），09:20:06 那轮则是
#: 全 ``SZ002xxx``（ST同德 / 保龄宝 / 辉煌科技 …）—— 都是页面尚未刷新时的**默认占位列表**，
#: 与真榜无关。真榜实测**段数恒为 4~6**（09-23 快照 5 段 / 09-24 快照 6 段：SH600/SH601/SH603/
#: SZ000/SZ002/SZ300 混合，逐轮换血），与前 20 真实热股**不可能清一色同一段**互为印证。
#: 故判据取「整榜同段」而非某个固定前缀 —— 占位段会变（000 -> 002），固定前缀必漏检。
THS_POI_SEGMENT_LEN = 5

# --- 财联社 ---
CLS_QUERY = "app=cailianpress&os=android&sv=835"
CLS_URL = "https://api3.cls.cn/v1/hot_stock?" + CLS_QUERY + "&sign={sign}"
CLS_HEADERS = {"Referer": "https://www.cls.cn/"}

# --- 通达信 ---
TDX_URL = "https://pul.tdx.com.cn/TQLEX?Entry=JNLPSE.hotStockList&RI="
TDX_BODY = '[{"listType":"0","cycle":"0"}]'
TDX_HEADERS = {"Content-Type": "text/plain;charset=UTF-8",
               "Referer": "https://pul.tdx.com.cn/site/app/gzhbd/tdx-topsearch/page-main.html"}

# --- 开盘啦（只保留复盘人气榜；原盘中人气榜已去掉） ---
KPH_URL = ("https://apphq.longhuvip.com/w1/api/index.php?Order=1&a=GetHotPHB"
           "&st=50&apiv={apiv}&Type={tp}&c=StockBidYiDong")
KPH_HEADERS = {"Accept": "*/*",
               "User-Agent": "lhb/5.9.3 (com.kaipanla.www; build:0; iOS 15.4.0) Alamofire/5.9.3"}
#: 开盘啦子榜：(顶层键, Type, apiv, 中文名)；**只保留复盘榜**，
#: 原盘中榜 (``pz``, 1, ``w21``) 已彻底去掉、不再抓取
KPH_BOARDS = (("fp", 13, "w28", "复盘人气榜"),)

# --- 55188（理想股票技术论坛：主力排名 + 人气热榜 + 龙头，三张榜各取前 10） ---
SJ88_URL = "https://www.55188.com/sec.php?action=overview"
SJ88_HEADERS = {"Accept": "application/json", "Referer": "https://www.55188.com/sec.php"}
SJ88_RB_URL = "https://eq.10jqka.com.cn/open/api/hot_list/v1/hot_stock/a/hour/data.txt"
SJ88_RB_HEADERS = {"Referer": "https://eq.10jqka.com.cn/"}
#: 精选板块（龙头榜用）：板块列表 + 某板块成分股（默认「最正宗」视图，前 10 行即龙一~龙十）
SJ88_BLOCKS_URL = "https://www.55188.com/sec.php?action=blocks&sort=1&order=1"
SJ88_STOCKS_URL = "https://www.55188.com/sec.php?action=block_stocks"
SJ88_BLOCKS_HEADERS = {"Accept": "application/json",
                       "Referer": "https://www.55188.com/sec.php",
                       "X-Requested-With": "XMLHttpRequest"}
#: 行徽标「龙一」~「龙十」-> 名次
SJ88_LEAD_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
#: 55188 三张子榜：(顶层键, 中文名)；主力排名取 main_force.all(沪深A股)，人气热榜取 stock_list，
#: 龙头取各精选板块行徽标（同一只股票出现在多个板块时取其最好名次）
SJ88_BOARDS = (("zl", "主力排名"), ("rb", "人气热榜"), ("ld", "龙头"))

# --- 百度财经热搜（A 股 · 热搜 tab · 今日榜；**反向因子**，只取前 10） ---
#: 页面 finance.baidu.com/hotlist 是前端渲染，直接抓 XHR 接口；market=ab 即 A 股、
#: type=day 即今日、day=口径日(YYYYMMDD)、hour 取收盘后
BAIDU_URL = ("https://finance.pae.baidu.com/selfselect/listsugrecomm"
             "?tn=wisexmlnew&dsp=iphone&product=search&style=tablelist"
             "&market=ab&type=day&day={day}&hour=15&pn=0&rn=&finClientType=pc")
#: 接口有风控：普通 requests 会命中 ``403 hit risk``（TLS 指纹被判为非浏览器），
#: 须用 curl_cffi 模拟浏览器指纹（见 ``fetch_baidu``）；``dsp=iphone`` 本就对应移动端，
#: 故 UA 用 iPhone 保持自洽
BAIDU_HEADERS = {
    "Referer": "https://finance.baidu.com/",
    "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_4 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"),
}
#: 该接口返回条数多于 10（实测 17+），必须按 body 顺序截取前 BAIDU_TOP_N 条
BAIDU_TOP_N = 10

# --- 东方财富「涨停池」（为 ① 龙头封单量 提供「封单 / 流通盘」比例） ---
#: 55188 三个端点均无「封单量 / 流通盘」字段，故 ①（龙头股封单 > 流通盘 5%）须跨源补数：
#: 从东财涨停池按口径日取全市场涨停股，用「封单金额 ÷ 流通市值」近似「封单 / 流通盘」。
#: 接口按 ``date=YYYYMMDD`` 选当日涨停池（15 个交易日内可查）；非交易日/无数据时会回退到
#: 最近一个有数据的交易日（``data.qdate`` 恒为最近交易日、不作准，仅以 ``date`` 选择）
EM_ZT_URL = ("https://push2ex.eastmoney.com/getTopicZTPool"
             "?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt"
             "&Pageindex=0&pagesize=300&sort=fbt:asc&date={day}&_={ms}")
EM_ZT_HEADERS = {"Accept": "*/*", "Referer": "https://quote.eastmoney.com/"}

# --- 腾讯行情（只用于给东财榜单补名称） ---
TENCENT_URL = "https://qt.gtimg.cn/q={codes}"
TENCENT_HEADERS = {"Referer": "https://gu.qq.com/"}
#: 一次补名的代码个数
TENCENT_BATCH = 60

#: market 字段 -> 交易所前缀（55188 人气热榜 17/33/151、通达信 1/0）
MARKET_MAP = {"151": "BJ", "17": "SH", "33": "SZ", "1": "SH", "0": "SZ",
              "sh": "SH", "sz": "SZ", "bj": "BJ"}

#: 计分平台（5 个）-> 抓取播报用名称（顺序即输出顺序）
SCORING_PLATFORMS = (("em", "东方财富"), ("tgb", "淘股吧"),
                     ("kph", "开盘啦"), ("sj88", "55188"), ("jygs", "韭研公社"))

#: 仅抓取留档、**不参与计分**的平台（比照通达信）：快照仍抓取落盘，因子脚本不读取、不计分
ARCHIVE_PLATFORMS = (("ths_poi", "同花顺·指标平台"), ("cls", "财联社"), ("tdx", "通达信"))

#: 附加数据（**不进 cover_platforms、不计 rank_score**）：百度热搜前 10 是反向因子，
#: 由因子脚本对命中者扣分（见《多平台热门股票数据说明》§9），这里只如实落盘；
#: 东财涨停池为 ① 龙头封单量 跨源补「封单 / 流通盘」比例
EXTRA_BOARDS = (("baidu", "百度热搜"), ("em_zt", "东财涨停池"))

#: 抓取平台 = 计分平台 + 仅留档平台
CRAWL_PLATFORMS = SCORING_PLATFORMS + ARCHIVE_PLATFORMS

#: 快照顶层键 -> 抓取播报用名称（顺序即抓取与输出顺序）= 抓取平台 + 附加榜单
PLATFORMS = CRAWL_PLATFORMS + EXTRA_BOARDS

#: 计分平台中文名（去重，5 个）：新上榜播报按平台聚合，同平台多榜只算 1 个平台
PLATFORM_LABELS = tuple(dict.fromkeys(label.split("·")[0] for _, label in SCORING_PLATFORMS))

#: 仅留档平台：**照旧抓取落盘，但任何可见输出都不出现**（快照逐平台播报、失败/占位清单都过滤掉）
ARCHIVE_KEYS = frozenset(key for key, _ in ARCHIVE_PLATFORMS)
ARCHIVE_LABELS = frozenset(label for _, label in ARCHIVE_PLATFORMS)


# ------------------------------ 工具 ------------------------------

def to_int(value):
    """任意标量 -> int；非法返回 None。"""
    if value is None:
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def to_float(value):
    """任意标量 -> float；非法返回 None。"""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def norm_code(raw, market=None):
    """平台代码 -> 统一写法 ``SH601091`` / ``SZ000993`` / ``BJ430047``；无法识别返回 None。

    接受 ``sh601091`` / ``601091.SH`` / ``601091``（此时用 market 字段判交易所，
    再不行按号段推断：4/8 -> 北交所，6/9 -> 沪市，其余 -> 深市）。
    """
    s = re.sub(r"[^0-9A-Za-z]", "", str(raw or "")).upper()
    m = re.match(r"^(?:(SH|SZ|BJ))?(\d{6})(?:(SH|SZ|BJ))?$", s)
    if not m:
        return None
    mkt = m.group(1) or m.group(3)
    num = m.group(2)
    if not mkt and market is not None:
        mkt = MARKET_MAP.get(str(market).strip().lower())
    if not mkt:
        if num[0] in "48":
            mkt = "BJ"
        elif num[0] in "69":
            mkt = "SH"
        else:
            mkt = "SZ"
    return mkt + num


def valid_rank(value, top_n):
    """名次 -> 1~top_n 的整数；越界/非法返回 None。"""
    rank = to_int(value)
    if rank is None or not 1 <= rank <= top_n:
        return None
    return rank


def sj88_lead_rank(text):
    """55188 精选板块行徽标「龙一」~「龙十」-> 1~10；其它文本返回 None。"""
    s = str(text or "").strip()
    if len(s) == 2 and s[0] == "龙":
        return SJ88_LEAD_DIGITS.get(s[1])
    return None


def strip_tags(html):
    """剥掉 HTML 标签与实体，压缩空白。"""
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def http_get_json(session, url, timeout, headers=None):
    resp = session.get(url, headers=headers or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ------------------------------ 名称缓存 ------------------------------

def load_names_cache():
    """读 names_cache.json（代码->名称 与 名称->代码 混存）；不存在或损坏则返回空表。"""
    if not os.path.exists(NAMES_CACHE_PATH):
        return {}
    try:
        with open(NAMES_CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as exc:                       # noqa: BLE001 - 缓存损坏不该中断抓取
        print("  [警告] 名称缓存读取失败(%s)，本次不使用缓存" % exc)
        return {}


def save_names_cache(cache):
    """合并写回 names_cache.json（只新增/更新 代码->名称）。"""
    if not cache:
        return
    try:
        with open(NAMES_CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=0)
    except Exception as exc:                       # noqa: BLE001
        print("  [警告] 名称缓存写回失败(%s)" % exc)


def fill_names(session, codes, timeout, cache, top_n):
    """用腾讯行情给（东财）榜单补股票名称，带本地缓存；返回补齐的 {代码: 名称}。"""
    need = [c for c in codes if not cache.get(c)]
    for i in range(0, len(need), TENCENT_BATCH):
        query = ",".join(c.lower() for c in need[i:i + TENCENT_BATCH])
        try:
            resp = session.get(TENCENT_URL.format(codes=query),
                               headers=TENCENT_HEADERS, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = "gbk"
        except Exception as exc:                   # noqa: BLE001
            print("  [警告] 腾讯名称接口失败(%s)，本批只留代码" % exc)
            continue
        for line in resp.text.split(";"):
            m = re.match(r'\s*v_([a-z]{2}\d{6})="(.*)"', line.strip())
            if not m:
                continue
            parts = m.group(2).split("~")
            if len(parts) > 1 and parts[1].strip():
                cache[m.group(1).upper()] = parts[1].strip()
        time.sleep(0.2)
    return {code: cache.get(code, "") for code in codes}


# ----------------- 五平台抓取 + 三留档（同花顺/财联社/通达信仅留档、不参与计分） -----------------

def fetch_em(session, timeout, top_n, meta):
    """东方财富「人气榜」前 top_n。"""
    resp = session.post(EM_URL, json=EM_BODY, headers=EM_HEADERS, timeout=timeout)
    resp.raise_for_status()
    items = (resp.json() or {}).get("data") or []
    out = {}
    for idx, item in enumerate(items):
        item = item or {}
        code = norm_code(item.get("sc"))
        rank = valid_rank(item.get("rk"), top_n) or valid_rank(idx + 1, top_n)
        if not code or rank is None:
            continue
        # 名次变化 = 昨日名次(hisRc) - 当前名次调整量(rc)，与交易所口径一致（0 表示持平）
        out[code] = {"rank": rank,
                     "chg": (to_int(item.get("hisRc")) or 0) - (to_int(item.get("rc")) or 0),
                     "name": ""}
    return out


def fetch_tgb(session, timeout, top_n, meta):
    """淘股吧「实时热搜」+「24h热搜」前 top_n（页面 4 张表，取前两张个股表）。"""
    resp = session.get(TGB_URL, headers=TGB_HEADERS, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    boards = []
    for table in re.findall(r"<table[^>]*>(.*?)</table>", resp.text, re.S):
        header, rows = None, []
        for raw_row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", raw_row, re.S)]
            if not cells:
                continue
            if header is None and cells[0].startswith("排名"):
                header = cells
                continue
            if header and len(cells) >= 5:
                rows.append((cells, raw_row))
        if header and len(header) > 1 and "个股" in header[1]:
            boards.append(rows)
    out = {}
    for key, rows in zip(TGB_BOARD_KEYS, boards):
        board = {}
        for cells, raw_row in rows:
            codes = re.findall(r"quotes/([A-Za-z]{2}\d{6})", raw_row)
            code = norm_code(codes[0]) if codes else None
            rank = valid_rank(cells[0], top_n)
            if not code or rank is None:
                continue
            board[code] = {"rank": rank,
                           "name": cells[1].split(" ")[0],
                           "today": cells[3],
                           "week": cells[4]}
        out[key] = board
    return out


class PlaceholderBoard(Exception):
    """盘前占位假榜：页面尚未刷新、返回的是默认列表（``fetch_ths_poi`` 判出后抛出）。

    与普通抓取失败的区别在于**不沿用旧快照** —— 占位榜是「榜单尚无当前值」，而旧快照是
    上一轮（甚至上一交易日）的旧榜，沿用会把过期名次当成当前值写进通达信通道；故按空榜处理。
    """


def fetch_ths_poi(session, timeout, top_n, meta):
    """同花顺「指标平台·热门股票」前 top_n（服务端渲染 HTML，无 xhr 接口）。

    页面左侧导航的个股链接形如
    ``<a ... url="/optimal/index/default/code/002614/"><span>奥佳华</span></a>``，
    **出现顺序即名次**（实测全页仅 20 个 code 链接，且与浏览器所见一致）；
    返回 ``{代码: {"rank": n, "name": 名称}}``，落盘为顶层键 ``ths_poi``。

    盘前该页会返回**占位假榜**（20 只全部落在同一个市场段，见 ``THS_POI_SEGMENT_LEN``）：
    此时抛 ``PlaceholderBoard``，由 ``run()`` 落空榜且不沿用旧快照。
    """
    resp = session.get(THS_POI_URL, headers=THS_POI_HEADERS, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    out = {}
    for idx, (num, name) in enumerate(THS_POI_ITEM_RE.findall(resp.text)):
        code = norm_code(num)
        rank = valid_rank(idx + 1, top_n)
        if not code or rank is None:
            continue
        out[code] = {"rank": rank, "name": re.sub(r"\s+", "", name)}
    segments = {code[:THS_POI_SEGMENT_LEN] for code in out}
    if out and len(segments) == 1:
        raise PlaceholderBoard(
            "疑似盘前占位假榜（%d 只全为 %s 段）" % (len(out), segments.pop()))
    return out


def fetch_cls(session, timeout, top_n, meta):
    """财联社「热榜」前 top_n（接口给 30 条，名次 = 下标 + 1）。"""
    sign = hashlib.md5(hashlib.sha1(CLS_QUERY.encode()).hexdigest().encode()).hexdigest()
    data = http_get_json(session, CLS_URL.format(sign=sign), timeout, CLS_HEADERS) or {}
    errno = data.get("errno")
    if errno not in (0, None):
        raise RuntimeError("财联社接口返回 errno=%s" % errno)
    out = {}
    for idx, item in enumerate((data.get("data") or [])[:top_n]):
        stock = (item or {}).get("stock") or {}
        code = norm_code(stock.get("StockID"))
        if not code:
            continue
        out[code] = {"rank": idx + 1,
                     "chg": stock.get("RiseRange"),
                     "name": (stock.get("name") or "").strip()}
    return out


def fetch_tdx(session, timeout, top_n, meta):
    """通达信「人气榜」前 top_n（响应为「表头行 + 数据行」的二维数组）。"""
    resp = session.post(TDX_URL, data=TDX_BODY.encode("utf-8"),
                        headers=TDX_HEADERS, timeout=timeout)
    resp.raise_for_status()
    rows = resp.json() or []
    out = {}
    header = None
    for row in rows:
        if not isinstance(row, list):
            continue
        if header is None:
            if "sec_code" in row:                  # 表头行（前面还有一行 [0,"",100,"",""]）
                header = row
            continue
        rec = dict(zip(header, row))
        code = norm_code(rec.get("sec_code"), rec.get("market"))
        rank = valid_rank(rec.get("ranking"), top_n)
        if not code or rank is None:
            continue
        out[code] = {"rank": rank,
                     "hot": to_int(rec.get("totalCount")),
                     "chg": rec.get("chg"),
                     "name": (rec.get("stock_name") or "").strip()}
        if not meta.get("date") and rec.get("occur_time"):
            meta["date"] = str(rec["occur_time"])[:10]      # 榜单实际数据日
    return out


def _parse_kph_board(data, top_n):
    """开盘啦单个榜单响应 -> {代码: 条目}；条目字段见 fetch_kph。"""
    out = {}
    for item in data.get("List") or []:
        if not isinstance(item, list) or len(item) < 5:
            continue
        code = norm_code(item[0])
        rank = valid_rank(item[4], top_n)
        if not code or rank is None:
            continue
        out[code] = {"rank": rank,
                     "chg": to_int(item[3]),            # 名次变化（与东财 chg 同义）
                     "zf": item[2],                     # 涨幅%
                     "name": str(item[1] or "").strip()}
    return out


def fetch_kph(session, timeout, top_n, meta):
    """开盘啦「复盘人气榜」取前 top_n（原「盘中人气榜」已去掉，不再抓取）。

    接口 ``Type=13&apiv=w28``；List 每行为 ``[代码, 名称, 涨幅%, 排名变化, 名次, 0, 0]``
    （返回 50 条，代码不带市场前缀）。返回 ``{"fp": {...}}``。
    """
    out = {}
    for board, tp, apiv, label in KPH_BOARDS:
        url = KPH_URL.format(tp=tp, apiv=apiv)
        try:
            data = http_get_json(session, url, timeout, KPH_HEADERS) or {}
        except Exception as exc:                        # noqa: BLE001
            print("    [开盘啦·%s] 抓取失败：%s" % (label, exc))
            data = {}
        board_out = _parse_kph_board(data, top_n)
        if board_out:
            out[board] = board_out
        if not meta.get("date") and data.get("Day"):
            meta["date"] = str(data["Day"])[:10]        # 榜单实际数据日
    return out


def fetch_jygs(session, timeout, top_n, meta):
    """韭研公社「异动图」红股（第 7 平台 · 红股没有 1~20 名次，只贡献覆盖平台数）。

    异动图是一张图片，识别链路（登录态 cookie -> Playwright 抓图 -> OpenCV 红墨比例 + OCR）
    封装在同目录 ``a_fetch_jygs_red.py``，按口径日缓存，当日首次识别后每轮直接复用；
    识别失败会沿用旧缓存并返回，绝不抛异常拖垮其它平台。

    返回 ``{SH603636: "南威软件", ...}``（代码写法与其它平台一致，值即名称）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import a_fetch_jygs_red                 # 惰性导入：playwright/cv2 等重依赖只在需要时加载

    date = str(meta.get("date") or "").strip() or datetime.now().strftime("%Y-%m-%d")
    out = {}
    for inst, name in (a_fetch_jygs_red.fetch_red_stocks(date) or {}).items():
        code = norm_code(inst)
        if code:
            out[code] = str(name or "").strip()
    return out


#: 55188 三张榜只取前 10（用户口径：主力排名前 10 + 人气热榜前 10 + 龙头龙一~龙十）
SJ88_TOP_N = 10

#: 龙头榜板块梯队门槛：板块内带「龙N」徽标的行不足 4 只 = 梯队不完整，整块放弃
#: （既不进 ld 龙头榜、也不进 leaders 明细）
SJ88_MIN_LEADERS = 4


def fetch_sj88(session, timeout, top_n, meta):
    """55188（理想股票技术论坛）「主力排名」+「人气热榜」+「龙头」各取前 10。

    主力排名 = ``sec.php?action=overview`` 的 ``main_force.all``（沪深A股 100 条）→ ``sj88.zl``；
              名次取数组下标 + 1（接口自带 ``rank`` 字段会随刷新在 1/2 间漂移，不可作准）
    人气热榜 = 同花顺 hot_stock 接口的 ``data.stock_list``（100 条）→ ``sj88.rb``；
              名次取接口 order / 下标 + 1
    龙头     = 精选板块 ``block_stocks`` 各板块默认「最正宗」视图前 10 行的行徽标
              （龙一~龙十）→ ``sj88.ld``；同一只股票出现在多个板块时取其最好名次。
              **板块梯队门槛**：板块内带「龙N」徽标的行不足 4 只 = 梯队不完整，该板块整体
              放弃（既不进 ``ld`` 榜、也不进 ``leaders`` 明细）

    三张榜各自独立落盘为 ``{"zl": {...}, "rb": {...}, "ld": {...}}``；单张榜失败不影响另两张。

    另附带落三份市场全景（与三张榜相互独立，解析失败/缺失不影响三榜；均**不参与计分**）：
      ``ladder``  连板梯队 -> ④ 涨停时间节奏（``first_limit_up`` / ``last_limit_up`` 为 Unix 秒，
                  可直接判「早盘 10 点前批量封板」与「尾盘偷袭」，两者相差大即中途炸板回封）
      ``sectors`` 热门板块 -> ② 板块内涨停家数（``limit_up_count`` 即跟风小弟数量，≥3 视为联动）
      ``leaders`` 板块龙头明细 -> ③ 新老龙头交替（按板块存 龙一~龙十 的 ``board`` 连板串 /
                  ``broken`` 是否炸板 / ``pct`` 涨幅 / ``amplitude`` 振幅，供下游自行判
                  「老龙头高位震荡 + 新小弟卡位涨停」；取自上文 ``block_stocks`` 同一批响应，零额外请求）
    """
    limit = min(top_n, SJ88_TOP_N)
    out = {}
    overview = None
    try:
        data = overview = http_get_json(session, SJ88_URL, timeout, SJ88_HEADERS) or {}
        board = {}
        for idx, item in enumerate(((data.get("main_force") or {}).get("all") or [])[:limit]):
            item = item or {}
            code = norm_code(item.get("code"))
            if not code:
                continue
            board[code] = {"rank": idx + 1,
                           "name": str(item.get("name") or "").strip(),
                           "main_force_pct": item.get("main_force_pct")}
        if board:
            out["zl"] = board
        if not meta.get("date") and data.get("trade_date"):
            meta["date"] = str(data["trade_date"])[:10]     # 榜单实际数据日
    except Exception as exc:                                # noqa: BLE001
        print("    [55188·主力排名] 抓取失败：%s" % exc)

    try:
        data = http_get_json(session, SJ88_RB_URL, timeout, SJ88_RB_HEADERS) or {}
        if data.get("status_code") not in (0, None) and data.get("code") != 20000:
            raise RuntimeError("接口 status_code=%s" % data.get("status_code"))
        board = {}
        stocks = ((data.get("data") or {}).get("stock_list") or [])[:limit]
        for idx, st in enumerate(stocks):
            st = st or {}
            code = norm_code(st.get("code"), st.get("market"))
            rank = valid_rank(st.get("order"), limit) or valid_rank(idx + 1, limit)
            if not code or rank is None:
                continue
            board[code] = {"rank": rank, "name": str(st.get("name") or "").strip()}
        if board:
            out["rb"] = board
    except Exception as exc:                                # noqa: BLE001
        print("    [55188·人气热榜] 抓取失败：%s" % exc)

    try:
        blocks = http_get_json(session, SJ88_BLOCKS_URL, timeout, SJ88_BLOCKS_HEADERS) or {}
        board, leaders, plates, skipped, failed = {}, {}, 0, 0, 0
        for plate in (blocks.get("rows") or []):
            pid = str((plate or {}).get("id") or "").strip()
            if not pid:
                continue
            url = "%s&plate=%s&order=1&st=%d&index=0" % (SJ88_STOCKS_URL, pid, limit)
            try:
                page = http_get_json(session, url, timeout, SJ88_BLOCKS_HEADERS) or {}
            except Exception as exc:                        # noqa: BLE001 - 单板块失败跳过
                failed += 1
                print("    [55188·龙头] 板块 %s 抓取失败：%s" % (pid, exc))
                continue
            plates += 1
            pname = str((plate or {}).get("name") or "").strip() or pid
            lead_rows = []
            for row in (page.get("rows") or [])[:limit]:
                row = row or {}
                code = norm_code(row.get("code"))
                rank = sj88_lead_rank(row.get("lead"))
                if not code or rank is None or rank > limit:
                    continue
                # ③ 新老龙头交替：按板块落 龙一~龙十 明细（连板/炸板/涨幅/振幅），
                # 供下游自行判「老龙头高位震荡 + 新小弟卡位涨停」；不参与计分。
                lead_rows.append({"rank": rank,
                                  "instrument": code,
                                  "name": str(row.get("name") or "").strip(),
                                  "lead": str(row.get("lead") or "").strip(),
                                  "board": row.get("board"),
                                  "broken": row.get("broken"),
                                  "pct": to_float(row.get("pct")),
                                  "amplitude": to_float(row.get("amplitude"))})
            # 板块梯队门槛：带「龙N」徽标的龙头不足 4 只 = 梯队不完整，整块放弃
            # （既不进 ld 龙头榜、也不进 leaders 明细）。
            if len(lead_rows) < SJ88_MIN_LEADERS:
                skipped += 1
                print("    [55188·龙头] 板块 %s（%s）龙头仅 %d 只 < %d，跳过"
                      % (pid, pname, len(lead_rows), SJ88_MIN_LEADERS))
                continue
            lead_rows.sort(key=lambda x: x["rank"])
            leaders[pname] = lead_rows
            for r in lead_rows:                             # 多板块上榜取最好名次
                code = r["instrument"]
                old = board.get(code)
                if old is None or r["rank"] < old["rank"]:
                    board[code] = {"rank": r["rank"], "name": r["name"]}
        if board:
            out["ld"] = board
        elif plates and failed == plates:
            raise RuntimeError("%d 个板块均抓取失败" % plates)
        if skipped:
            print("    [55188·龙头] %d 个板块梯队不足（龙头 < %d 只），整块跳过"
                  % (skipped, SJ88_MIN_LEADERS))
        if failed:
            print("    [55188·龙头] %d 个板块抓取失败，%d 个板块成功"
                  % (failed, plates))
        if leaders:
            out["leaders"] = leaders
    except Exception as exc:                                # noqa: BLE001
        print("    [55188·龙头] 抓取失败：%s" % exc)

    # 附加：涨停时间节奏（④）与板块内涨停家数（②）——取自上面那份 overview 响应，不额外发请求。
    # 单独 try/except，解析异常不影响已落盘的 zl/rb/ld 三榜。
    if overview:
        try:
            ladder = []
            for tier in (overview.get("limit_ladder") or []):
                tier = tier or {}
                stocks = []
                for st in (tier.get("stocks") or []):
                    st = st or {}
                    inst = norm_code(st.get("code"), st.get("symbol"))
                    if not inst:
                        continue
                    stocks.append({"instrument": inst,
                                   "name": str(st.get("name") or "").strip(),
                                   "first_limit_up": to_int(st.get("first_limit_up")),
                                   "last_limit_up": to_int(st.get("last_limit_up")),
                                   "plates": st.get("plates") or []})
                if stocks:
                    ladder.append({"board": to_int(tier.get("board")),
                                   "count": to_int(tier.get("count")),
                                   "stocks": stocks})
            if ladder:
                out["ladder"] = ladder

            sectors = {}
            for sec in (overview.get("hot_sectors") or []):
                sec = sec or {}
                name = str(sec.get("name") or "").strip()
                if not name:
                    continue
                stocks = []
                for st in (sec.get("stocks") or []):
                    st = st or {}
                    inst = norm_code(st.get("code"))
                    if inst:
                        stocks.append({"instrument": inst,
                                       "name": str(st.get("name") or "").strip(),
                                       "board": to_int(st.get("board"))})
                sectors[name] = {"limit_up_count": to_int(sec.get("limit_up_count")),
                                 "max_board": to_int(sec.get("max_board")),
                                 "reason": str(sec.get("reason") or "").strip(),
                                 "stocks": stocks}
            if sectors:
                out["sectors"] = sectors
        except Exception as exc:                            # noqa: BLE001
            print("    [55188·涨停梯队/板块] 解析失败：%s" % exc)
    return out


def fetch_baidu(session, timeout, top_n, meta):
    """百度财经「热搜」榜（A 股 · 今日）前 10 —— **反向因子**，不进 cover_platforms 计数。

    页面 ``finance.baidu.com/hotlist?mainTab=hotSearch&market=ab`` 是前端渲染，故直接抓
    XHR 接口（``market=ab`` = A 股、``type=day`` = 今日、``day`` = 口径日）；接口返回条数
    多于 10，按 body 顺序截取前 ``min(top_n, BAIDU_TOP_N)`` 条，数组下标 + 1 即名次。

    返回 ``{SH601091: {"rank": 1, "rank_chg": 0, "name": "C沈鼓", "sector": "专用设备",
                       "chg": "-21.01%", "hot": "2120000"}, ...}``
    （``hot`` 落接口原始热度值，页面显示的 ``210.1w`` 是二次格式化结果）

    该接口有 TLS 指纹风控（普通 ``requests`` 一律 ``403 hit risk``），故用 curl_cffi 模拟
    浏览器指纹；缺库时退回 ``session``（会 403，按抓取失败处理）。
    """
    day = re.sub(r"[^0-9]", "", str(meta.get("date") or ""))
    if len(day) != 8:
        day = datetime.now().strftime("%Y%m%d")
    url = BAIDU_URL.format(day=day)
    if curl_requests is None:
        data = http_get_json(session, url, timeout, BAIDU_HEADERS) or {}
    else:
        resp = curl_requests.get(url, headers=BAIDU_HEADERS, impersonate="chrome",
                                 timeout=timeout)
        resp.raise_for_status()
        data = resp.json() or {}
    body = ((data.get("Result") or {}).get("list") or {}).get("body") or []
    limit = min(top_n, BAIDU_TOP_N)
    out = {}
    for idx, item in enumerate(body[:limit]):
        item = item or {}
        # market=ab 只返回 A 股；仍防御性地丢弃取不到代码的记录（如误配 market=all 时的港美股）
        code = norm_code(item.get("code"), item.get("exchange"))
        if not code:
            continue
        out[code] = {"rank": idx + 1,
                     "rank_chg": to_int(item.get("rankDiff")),
                     "name": str(item.get("name") or "").strip(),
                     "sector": str(item.get("blockName") or "").strip(),
                     "chg": item.get("pxChangeRate"),
                     "hot": item.get("heat")}
    return out


def fetch_em_zt(session, timeout, top_n, meta):
    """东方财富「涨停池」——为 ① 龙头封单量 跨源补「封单 / 流通盘」比例。

    55188 三个端点经全量扫描均无「封单量 / 流通盘」字段，故按口径日从东财涨停池取全市场
    涨停股，对每只算 ``seal_ratio = fund / ltsz``（封单金额 ÷ 流通市值，近似「封单 / 流通盘」），
    下游据此判「龙头股封单 > 流通盘 5%」。**不进 cover_platforms、不计 rank_score**。

    返回 ``{SH600293: {"name": "三峡新材", "fund": 59982095.0, "ltsz": 8188814951.35,
                       "seal_ratio": 0.007324, "board": 1, "sector": "基础建设"}, ...}``
    ``fund`` 封单金额(元) / ``ltsz`` 流通市值(元) / ``board`` 连板数 / ``sector`` 东财行业板块。
    """
    day = re.sub(r"[^0-9]", "", str(meta.get("date") or ""))
    if len(day) != 8:
        day = datetime.now().strftime("%Y%m%d")
    url = EM_ZT_URL.format(day=day, ms=int(time.time() * 1000))
    data = http_get_json(session, url, timeout, EM_ZT_HEADERS) or {}
    out = {}
    for item in ((data.get("data") or {}).get("pool") or []):
        item = item or {}
        code = norm_code(item.get("c"))            # 单代码按号段推断交易所（6/9->沪，4/8->北，余->深）
        if not code:
            continue
        fund = to_float(item.get("fund"))
        ltsz = to_float(item.get("ltsz"))
        out[code] = {"name": str(item.get("n") or "").strip(),
                     "fund": fund,
                     "ltsz": ltsz,
                     "seal_ratio": round(fund / ltsz, 6) if fund and ltsz else None,
                     "board": to_int(item.get("lbc")),
                     "sector": str(item.get("hybk") or "").strip()}
    return out


#: 平台 -> 抓取函数
FETCHERS = {"em": fetch_em, "tgb": fetch_tgb, "ths_poi": fetch_ths_poi,
            "cls": fetch_cls, "tdx": fetch_tdx, "kph": fetch_kph,
            "sj88": fetch_sj88, "jygs": fetch_jygs, "baidu": fetch_baidu,
            "em_zt": fetch_em_zt}


# ------------------------------ 主流程 ------------------------------

def load_prev_snapshot(path):
    """读上一次快照（失败平台回退用）；不存在/损坏返回空表。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as exc:                       # noqa: BLE001
        print("  [警告] 上次快照读取失败(%s)，失败平台将无历史数据可回退" % exc)
        return {}


def is_empty(key, value):
    """平台结果是否为空（淘股吧按两张子榜合并判断）。"""
    if not isinstance(value, dict):
        return True
    if key == "tgb":
        return not any(value.get(b) for b in TGB_BOARD_KEYS)
    return not value


def save_snapshot(snapshot, path):
    """原子落盘：先写临时文件再替换，避免写入中断损坏原快照。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False)
    os.replace(tmp, path)


def describe(key, value):
    """平台结果 -> 打印用描述。"""
    if key == "tgb":
        parts = ["%s %d 只" % (("实时" if b == "rt" else "24h"), len(value.get(b) or {}))
                 for b in TGB_BOARD_KEYS]
        return " / ".join(parts)
    if key == "ths_poi":
        return "%d 只（热门股票）" % len(value)
    if key == "kph":
        return " / ".join("%s %d 只" % (label.split("人气榜")[0], len(value.get(b) or {}))
                          for b, _, _, label in KPH_BOARDS)
    if key == "sj88":
        desc = " / ".join("%s %d 只" % (label, len(value.get(b) or {}))
                          for b, label in SJ88_BOARDS)
        extra = []
        if value.get("sectors"):
            extra.append("板块 %d 个" % len(value["sectors"]))
        if value.get("ladder"):
            extra.append("梯队 %d 档" % len(value["ladder"]))
        if value.get("leaders"):
            extra.append("龙头明细 %d 板块" % len(value["leaders"]))
        return desc + ("（附加全景：%s）" % "、".join(extra) if extra else "")
    if key == "jygs":
        return "%d 只红股（无名次）" % len(value)
    if key == "baidu":
        return "%d 只（A股热搜前 %d · 反向只扣分）" % (len(value), BAIDU_TOP_N)
    if key == "em_zt":
        return "%d 只涨停（封单金额 ÷ 流通市值，供 ① 判封单/流通盘）" % len(value)
    return "%d 只" % len(value)


# ------------------------------ 新上榜播报 ------------------------------

def flat_ranks(snapshot):
    """快照 -> {平台中文名: {代码: (最好名次, 名称)}}（同平台多榜单只取最好名次）。

    只遍历**计分平台**（``PLATFORM_LABELS``）：百度热搜是**附加反向榜**，故意不参与
    覆盖去重与新上榜播报（它命中反而扣分，混进来会污染「共振」语义）；仅留档平台
    （同花顺 / 财联社 / 通达信）不参与任何播报。
    """
    out = {label: {} for label in PLATFORM_LABELS}

    def put(label, code, rank, name):
        rank = to_int(rank)                 # 韭研红股没有名次：rank=None 也要登记（只算覆盖平台数）
        board = out[label]
        old = board.get(code)
        if old is None or (rank is not None and (old[0] is None or rank < old[0])):
            board[code] = (rank, (str(name).strip() if name else "") or (old[1] if old else ""))

    for code, val in (snapshot.get("em") or {}).items():
        val = val or {}
        put("东方财富", code, val.get("rank"), val.get("name"))
    tgb = snapshot.get("tgb") or {}
    for board in TGB_BOARD_KEYS:
        for code, val in (tgb.get(board) or {}).items():
            put("淘股吧", code, (val or {}).get("rank"), (val or {}).get("name"))
    kph = snapshot.get("kph") or {}
    for board, _, _, _ in KPH_BOARDS:
        for code, val in (kph.get(board) or {}).items():
            put("开盘啦", code, (val or {}).get("rank"), (val or {}).get("name"))
    sj88 = snapshot.get("sj88") or {}
    for board, _ in SJ88_BOARDS:
        for code, val in (sj88.get(board) or {}).items():
            put("55188", code, (val or {}).get("rank"), (val or {}).get("name"))
    for code, name in (snapshot.get("jygs") or {}).items():
        put("韭研公社", code, None, name)          # 红股无名次，只登记代码 + 名称
    return out


def fmt_rank(rank):
    """名次后缀；韭研红股没有 1~20 名次（rank=None），返回空串只显示平台名。"""
    return "#%d" % rank if rank is not None else ""


def load_seen(date):
    """读当日「已出现股票」状态；日期不一致（跨日）时清空重来。"""
    if date and os.path.exists(SEEN_PATH):
        try:
            with open(SEEN_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if (isinstance(data, dict) and data.get("date") == date
                    and isinstance(data.get("first_seen"), dict)):
                return data
        except Exception:                          # noqa: BLE001 - 状态损坏不该中断抓取
            pass
    return {"date": date, "first_seen": {}}


def save_seen(state):
    """写回当日状态。"""
    try:
        with open(SEEN_PATH, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=0)
    except Exception as exc:                       # noqa: BLE001
        print("  [警告] 当日状态写回失败(%s)" % exc)


def report_new(prev, snapshot):
    """与上一轮快照比对，播报本轮新进榜的股票（上一轮各平台都没上榜的）。"""
    date = snapshot.get("date") or ""
    cur_map = flat_ranks(snapshot)

    # 只与「同一口径日」的上一轮快照比对；跨日（如隔夜首轮）视为基线，不误报成新上榜
    same_day = bool(date) and (prev or {}).get("date") == date
    prev_codes = set()
    if same_day:
        for codes in flat_ranks(prev).values():
            prev_codes.update(codes)

    state = load_seen(date)
    seen = state["first_seen"]
    now_str = datetime.now().strftime("%H:%M:%S")

    print("-" * 68)
    if not prev_codes:
        print("新上榜：无可比对的同口径日上一轮快照（本轮作为基线）")
    else:
        new = {}
        for label in PLATFORM_LABELS:
            for code, (rank, name) in cur_map[label].items():
                if code in prev_codes:
                    continue
                rec = new.setdefault(code, {"name": "", "plats": []})
                if name and not rec["name"]:
                    rec["name"] = name
                rec["plats"].append((label, rank))
        if not new:
            print("新上榜：无（较上一轮 %s 无新进股票）" % (prev.get("fetched_at") or "上一次快照"))
        else:
            print("新上榜 %d 只（较上一轮 %s）："
                  % (len(new), prev.get("fetched_at") or "上一次快照"))
            for code, rec in sorted(new.items(),
                                   key=lambda kv: (-len(kv[1]["plats"]),
                                                   kv[1]["plats"][0][1] or 0,
                                                   kv[0])):
                first = seen.get(code)
                tag = "[新出现]" if not first else "[重回 · 首次 %s]" % first
                plats = " · ".join("%s%s" % (label, fmt_rank(rank)) for label, rank in rec["plats"])
                print("  %-10s %-10s %-20s %s" % (code, rec["name"] or "-", tag, plats))

    # 当日状态：在榜代码登记首现时间（新进榜的此刻才登记，故上面能区分新出现/重回）
    for codes in cur_map.values():
        for code in codes:
            seen.setdefault(code, now_str)
    state["date"] = date or state.get("date")
    save_seen(state)
    print("  当日累计上榜 %d 只（首现时间记于 %s）" % (len(seen), SEEN_NAME))


def run(args):
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    prev = load_prev_snapshot(args.out)
    cache = load_names_cache()

    meta = {}
    snapshot = {}
    failed, reused, placeholders = [], [], []

    for key, label in PLATFORMS:
        try:
            value = FETCHERS[key](session, args.timeout, args.top, meta)
            if is_empty(key, value):
                raise RuntimeError("返回空榜单")
            snapshot[key] = value
            if key not in ARCHIVE_KEYS:            # 留档平台只抓不报（可见输出不出现这三家）
                print("[%s] 成功：%s" % (label, describe(key, value)))
        except PlaceholderBoard as exc:             # 盘前占位假榜：判空落盘，且**不沿用旧快照**
            snapshot[key] = {}
            placeholders.append(label)
            if key not in ARCHIVE_KEYS:
                print("[%s] %s -> 判空不落盘（不沿用旧快照）" % (label, exc))
        except Exception as exc:                   # noqa: BLE001 - 单平台失败不拖垮整份快照
            failed.append(label)
            # 百度是反向因子（命中才扣分）、涨停池封单比例是当日快照，二者都会过期：
            # 失败时**不沿用旧快照**（§9.7），直接落空；其余平台照旧回退到上一次快照
            if (key not in ("baidu", "em_zt") and not args.no_cache
                    and not is_empty(key, prev.get(key))):
                snapshot[key] = prev[key]
                reused.append(label)
                if key not in ARCHIVE_KEYS:
                    print("[%s] 失败（%s），沿用上一次快照的 %s"
                          % (label, exc, describe(key, prev[key])))
            else:
                snapshot[key] = {"rt": {}, "h24": {}} if key == "tgb" else {}
                if key not in ARCHIVE_KEYS:
                    print("[%s] 失败（%s），且无历史数据可回退，落空榜" % (label, exc))

    # 东财榜单不带名称，用腾讯行情补齐（补齐失败仍保留代码，不影响因子）
    if snapshot.get("em"):
        names = fill_names(session, list(snapshot["em"]), args.timeout, cache, args.top)
        for code, rec in snapshot["em"].items():
            rec["name"] = names.get(code) or rec.get("name") or ""
        missing = sum(1 for rec in snapshot["em"].values() if not rec["name"])
        if missing:
            print("[东方财富] 仍有 %d 只未取到名称" % missing)
    save_names_cache(cache)

    # 口径日：--date > 通达信 occur_time / 开盘啦 Day / 55188 trade_date > 本机日期
    date = args.date or meta.get("date") or datetime.now().strftime("%Y-%m-%d")

    final = {"date": date,
             "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    for key, _ in PLATFORMS:
        final[key] = snapshot[key]

    save_snapshot(final, args.out)
    # 榜条目合计 = 计分平台（百度是附加反向榜，单独报数，不计入合计）；
    # 55188 只算 zl/rb/ld 三张榜，附加的 ladder / sectors 全景字段不计入
    total = 0
    for key, _ in SCORING_PLATFORMS:
        value = final.get(key)
        if not isinstance(value, dict):
            continue
        total += (sum(1 for b in SJ88_BOARDS if isinstance(value.get(b), dict))
                  if key == "sj88" else len(value))
    print("口径日 %s -> %s（计分平台 %d 个、榜条目合计 %d；"
          "另附百度热搜反向榜 %d 只、东财涨停池 %d 只）"
          % (date, args.out, len(SCORING_PLATFORMS), total,
             len(snapshot.get("baidu") or {}), len(snapshot.get("em_zt") or {})))

    report_new(prev, final)

    shown_ph = [lb for lb in placeholders if lb not in ARCHIVE_LABELS]
    if shown_ph:                           # 盘前占位假榜：已判空，不算失败（不影响返回码）
        print("盘前占位假榜（判空不落盘、不沿用旧快照）：%s" % "、".join(shown_ph))
    if failed:
        shown = [lb for lb in failed if lb not in ARCHIVE_LABELS]
        if shown:                          # 留档平台失败不上屏（不影响计分，也不进可见输出）
            print("失败平台：%s%s"
                  % ("、".join(shown), ("（已用历史快照回退）" if reused else "（无历史回退）")))
        return 1 if not reused or len(reused) < len(failed) else 0
    return 0


def run_loop(args):
    """常驻模式：按整 interval 秒对齐循环抓取（默认 10 分钟一轮），Ctrl+C 退出。"""
    interval = max(MIN_INTERVAL, args.interval)
    print("常驻模式：每 %d 秒抓一轮（Ctrl+C 退出）" % interval)
    try:
        while True:
            try:
                run(args)
            except Exception as exc:               # noqa: BLE001 - 单轮异常不中断循环
                print("本轮抓取异常：%s" % exc)
            # 对齐到下一个整 interval 边界（按墙钟对齐，避免逐轮累积漂移）
            now = time.time()
            nxt = (int(now // interval) + 1) * interval
            wait = max(1.0, nxt - now)
            print("下一轮 %s（%.0f 秒后）\n"
                  % (datetime.fromtimestamp(nxt).strftime("%H:%M:%S"), wait))
            time.sleep(wait)
    except KeyboardInterrupt:
        print("\n已退出常驻模式")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="五平台人气榜快照抓取（东财/淘股吧/开盘啦(仅复盘)/55188/韭研公社 五个计分平台）"
                    "+ 百度热搜（反向）")
    parser.add_argument("--out", default=OUT_PATH, help="快照输出路径（默认 last_good.json）")
    parser.add_argument("--date", default="", help="口径日 YYYY-MM-DD（默认取通达信/开盘啦/55188 接口的数据日）")
    parser.add_argument("--top", type=int, default=TOP_N, help="各榜名次上限（默认 %d）" % TOP_N)
    parser.add_argument("--timeout", type=int, default=TIMEOUT, help="单请求超时秒数（默认 %d）" % TIMEOUT)
    parser.add_argument("--no-cache", action="store_true",
                        help="平台失败时不回退上一次快照的该平台数据")
    parser.add_argument("--loop", action="store_true",
                        help="常驻，按 --interval 循环抓取并播报新上榜")
    parser.add_argument("--interval", type=int, default=LOOP_INTERVAL,
                        help="--loop 的间隔秒数（默认 %d，下限 %d）" % (LOOP_INTERVAL, MIN_INTERVAL))
    args = parser.parse_args()
    sys.exit(run_loop(args) if args.loop else run(args))


if __name__ == "__main__":
    main()
