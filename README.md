# Majsoul Paipu Harvester & Analyzer

*[中文说明 (Chinese README)](README.zh-CN.md)*

A lightweight Python toolkit that batch-downloads Mahjong Soul (雀魂) game records via paipu links (UUIDs) and produces multi-dimensional player statistics and archives, following the approach of [amae-koromo-scripts](https://github.com/SAPikachu/amae-koromo-scripts).

## Tech Stack

- **Fetching**: [mahjong_soul_api](https://github.com/MahjongRepository/mahjong_soul_api) talks to the Majsoul WebSocket API and calls `fetchGameRecord`
- **Protocol**: Protobuf definitions from the same library (`.proto` reference: amae-koromo-scripts)
- **Processing**: Python + Pandas; raw data stored as JSON, stats output as CSV/Excel

## Setup

```bash
# A virtual environment is recommended
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Dependencies (install mahjong_soul_api from Git if not on PyPI)
pip install -r requirements.txt
pip install git+https://github.com/MahjongRepository/mahjong_soul_api.git
```

## Project Layout

```
paipu_analyzer/
├── data/raw/          # Raw paipu JSON (written by the fetcher)
├── output/            # Final Excel reports
├── protocols/         # Protocol notes (the `ms` package is used in practice)
├── scripts/
│   ├── utils_url.py   # Phase 1: URL → UUID parsing
│   ├── fetcher.py     # Phase 2: download paipu → JSON
│   ├── analyzer.py    # Phase 3: JSON → per-game per-player stats
│   └── archiver.py    # Phase 4: aggregate by player → summary_report.xlsx
└── requirements.txt
```

## Usage

### 1. Extract UUIDs (Phase 1)

Accepts full URLs or bare UUIDs; automatically strips the `_a123...` viewpoint suffix.

```python
from scripts.utils_url import extract_uuid_from_url, extract_uuids_from_urls

uuid = extract_uuid_from_url("https://game.maj-soul.com/1/?paipu=xxxx-xxxx_a123")
urls = ["https://game.maj-soul.com/1/?paipu=uuid1", "uuid2"]
uuids = extract_uuids_from_urls(urls)
```

### 2. Download paipu (Phase 2)

Requires a **CN-server account** (only the CN server supports username/password login). Expired links (e.g. unsaved for over 30 days) are skipped and logged.

```bash
python -m scripts.fetcher -u your_email -p your_password "https://game.maj-soul.com/1/?paipu=UUID1" "UUID2"
# Default output dir is data/raw/, override with -o
```

### 3. Stats and archiving (Phase 3 + 4)

```bash
# Stats only, output CSV (optional)
python -m scripts.analyzer -i data/raw -o stats.csv

# Generate the player summary Excel report directly
python -m scripts.archiver -i data/raw -o output -f summary_report.xlsx
```

## Business Rules

- **UUID**: only the primary UUID before the underscore is kept; `_a123...` suffixes are ignored.
- **Player identity**: `account_id` is the unique key; the same player's nickname may differ across games.
- **Errors**: expired paipu links are skipped and logged, without interrupting the batch job.

## Metrics (Phase 3 / 4)

Stats logic follows [amae-koromo-scripts](https://github.com/SAPikachu/amae-koromo-scripts), parsing Record events game by game.

- **Basic**: initial score, final score, rank (1–4 by final score), win count, deal-in count
- **Advanced**: riichi rate, meld (fuuro) rate, no-ten/tenpai-at-draw rate (mokuten rate and average shanten can be added later)
- **Friendly (yūjin) games**: custom rules such as red fives can be detected from `head.config` (extensible in the analyzer)

**Detailed definitions**: [docs/统计指标说明.md](docs/统计指标说明.md) (Chinese).

## Example (sanitized — UUIDs, nicknames, and account IDs are all placeholders)

### Raw paipu JSON (`data/raw/*.json`, excerpt)

```json
{
  "head": {
    "uuid": "00000000-0000-0000-0000-000000000000",
    "accounts": [
      {"seat": 1, "account_id": 10000001, "nickname": "PlayerA"},
      {"seat": 2, "account_id": 10000002, "nickname": "PlayerB"},
      {"seat": 3, "account_id": 10000003, "nickname": "PlayerC"},
      {"seat": 4, "account_id": 10000004, "nickname": "PlayerD"}
    ],
    "result": {
      "players": [
        {"seat": 1, "total_point": 32000},
        {"seat": 2, "total_point": 28000},
        {"seat": 3, "total_point": 22000},
        {"seat": 4, "total_point": 18000}
      ]
    },
    "config": {}
  },
  "data": [
    {"name": ".lq.RecordNewRound", "data": {"chang": 0, "ju": 0}},
    {"name": ".lq.RecordDiscardTile", "data": {"seat": 0, "tile": "1m"}},
    {"name": ".lq.RecordHule", "data": {"seat": 0, "delta_scores": [8000, -8000, 0, 0]}}
  ]
}
```

### Stats output (`stats.csv`, excerpt)

| game_uuid | seat | account_id | nickname | initial_point | final_point | rank | wins | deal_in | riichi | melds | no_ten_tenpai |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 00000000-0000-... | 0 | 10000001 | PlayerA | 25000 | 32000 | 1 | 1 | 0 | 1 | 0 | 0 |
| 00000000-0000-... | 1 | 10000002 | PlayerB | 25000 | 28000 | 2 | 0 | 1 | 0 | 1 | 1 |
| 00000000-0000-... | 2 | 10000003 | PlayerC | 25000 | 22000 | 3 | 0 | 0 | 0 | 0 | 1 |
| 00000000-0000-... | 3 | 10000004 | PlayerD | 25000 | 18000 | 4 | 0 | 0 | 1 | 0 | 0 |

### Player summary (`summary_report.xlsx`, excerpt)

| account_id | nickname | games | avg_rank | win_rate | deal_in_rate | riichi_rate |
|---|---|---|---|---|---|---|
| 10000001 | PlayerA | 12 | 2.08 | 25.0% | 16.7% | 33.3% |
| 10000002 | PlayerB | 12 | 2.42 | 16.7% | 25.0% | 25.0% |

## References

- [amae-koromo-scripts](https://github.com/SAPikachu/amae-koromo-scripts) — stats logic and proto reference
- [mahjong_soul_api](https://github.com/MahjongRepository/mahjong_soul_api) — WebSocket and Protobuf
- [tensoul](https://github.com/Equim-chan/tensoul) / [tensoul-py](https://github.com/ssttkkl/tensoul-py) — paipu-fetching approach
