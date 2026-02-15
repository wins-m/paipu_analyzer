# 雀魂牌谱数据采集与分析 (Majsoul Paipu Harvester & Analyzer)

轻量级 Python 工具：通过雀魂牌谱链接（UUID）批量下载对局数据，并按 [amae-koromo-scripts](https://github.com/SAPikachu/amae-koromo-scripts) 思路做多维度选手统计与归档。

## 技术栈

- **抓取**: 使用 [mahjong_soul_api](https://github.com/MahjongRepository/mahjong_soul_api) 与雀魂 WebSocket 通信，调用 `fetchGameRecord`
- **协议**: 同上库的 Protobuf 定义（`.proto` 参考 amae-koromo-scripts）
- **处理**: Python + Pandas；原始数据存 JSON，统计结果存 CSV/Excel

## 环境准备

```bash
# 建议使用虚拟环境
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 依赖（mahjong_soul_api 若 PyPI 无则从 Git 安装）
pip install -r requirements.txt
pip install git+https://github.com/MahjongRepository/mahjong_soul_api.git
```

## 目录结构

```
paipu_analyzer/
├── data/raw/          # 原始牌谱 JSON（下载器写入）
├── output/            # 最终 Excel 报告
├── protocols/         # 协议说明（实际使用 ms 包）
├── scripts/
│   ├── utils_url.py   # Phase 1: URL → UUID 解析
│   ├── fetcher.py     # Phase 2: 下载牌谱 → JSON
│   ├── analyzer.py    # Phase 3: JSON → 每局每人统计
│   └── archiver.py    # Phase 4: 按选手聚合 → summary_report.xlsx
└── requirements.txt
```

## 使用步骤

### 1. 提取 UUID（Phase 1）

支持完整 URL 或仅 UUID；自动忽略 `_a123...` 视角后缀。

```python
from scripts.utils_url import extract_uuid_from_url, extract_uuids_from_urls

uuid = extract_uuid_from_url("https://game.maj-soul.com/1/?paipu=xxxx-xxxx_a123")
urls = ["https://game.maj-soul.com/1/?paipu=uuid1", "uuid2"]
uuids = extract_uuids_from_urls(urls)
```

### 2. 下载牌谱（Phase 2）

需**国服账号**（仅国服支持账号密码登录）。失效链接（如超 30 天未存盘）会跳过并打 Log。

```bash
python -m scripts.fetcher -u 你的邮箱 -p 你的密码 "https://game.maj-soul.com/1/?paipu=UUID1" "UUID2"
# 输出目录默认 data/raw/，可用 -o 指定
```

### 3. 统计与归档（Phase 3 + 4）

```bash
# 仅统计，输出 CSV（可选）
python -m scripts.analyzer -i data/raw -o stats.csv

# 直接生成选手汇总 Excel
python -m scripts.archiver -i data/raw -o output -f summary_report.xlsx
```

## 业务规则

- **UUID**: 只保留下划线前的主 UUID，忽略 `_a123...` 等后缀。
- **选手唯一性**: 以 `account_id` 为唯一标识；同一人在多局中昵称可不同。
- **异常**: 已失效的牌谱链接跳过并记录日志，不中断批量任务。

## 指标说明（Phase 3 / 4）

统计规则对齐 [amae-koromo-scripts](https://github.com/SAPikachu/amae-koromo-scripts)，逐局解析 Record 事件。

- **基础**: 初始分、终盘分、顺位（按终盘分 1～4）、和了次数、放铳次数
- **进阶**: 立直率、副露率、流局听牌率（默听率、平均向听数可后续扩展）
- **友人场**: 从 `head.config` 可识别赤宝牌等自定义规则（分析器可扩展）

**详细定义**见 [docs/统计指标说明.md](docs/统计指标说明.md)。

## 参考资源

- [amae-koromo-scripts](https://github.com/SAPikachu/amae-koromo-scripts) — 统计逻辑与 proto 参考
- [mahjong_soul_api](https://github.com/MahjongRepository/mahjong_soul_api) — WebSocket 与 Protobuf
- [tensoul](https://github.com/Equim-chan/tensoul) / [tensoul-py](https://github.com/ssttkkl/tensoul-py) — 牌谱获取思路
