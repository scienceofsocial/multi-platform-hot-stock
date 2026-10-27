# 多平台热门股票 · 五平台人气共振数据管线

抓取多平台（东方财富 / 淘股吧 / 韭研公社 / 55188 / 通达信等）的人气榜、龙头榜、涨停池，
合成共振分并落地到通达信自定义数据，附每日日报与变化时点分析。

> 本仓库为**代码与文档**托管。数据、日志、运行时 cookie 一律不入库（见 `.gitignore`）。

## 结构

| 文件 | 作用 |
|---|---|
| `a_fetch_hot_snapshot.py` | 主抓取：各平台榜单 -> 快照 `last_good.json` |
| `a_archive_hot_snapshot.py` | 按口径日归档快照 + 变化即追加 `hot_trace.jsonl` |
| `a_duopingtai_hot_factor.py` | 五平台共振分因子面板 |
| `a_export_tdx_hot_rank.py` | 导出通达信自定义数据 `.dat` + 公式 |
| `a_report_daily.py` | 每日日报 |
| `hot_trace_timeline.py` | 龙头榜全天变化时点明细表 |
| `ld_timeline_stats.py` | 变化时点统计（节奏/形态/龙头/只数） |
| `em_cookie.py` | 东方财富 cookie 提取/注入（Playwright） |

## 运行

Windows 计划任务驱动，入口 `run_hot_rank_daily.bat`。详见 `多平台热门股票数据说明.md`。

## 环境

- Python 3.11+（numpy / pandas / playwright / requests）
- 行情数据源：本机通达信 `C:\new_tdx`
