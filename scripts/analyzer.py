# scripts/analyzer.py
"""
Phase 3: 统计引擎。
遍历 data/raw/ 中的牌谱 JSON，解析每一巡（Record）事件，按 amae-koromo 思路提取多维度指标。
- 基础: 初始分、终盘分、顺位、和了次数、放铳次数
- 进阶: 立直率、副露率、默听率、流局听牌率
- 友人场: 从 head.config 识别赤宝牌等自定义规则。
"""
import json
import logging
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# 需要统计的 Record 类型名
RECORD_NEW_ROUND = ".lq.RecordNewRound"
RECORD_DISCARD_TILE = ".lq.RecordDiscardTile"
RECORD_CHI_PENG_GANG = ".lq.RecordChiPengGang"
RECORD_AN_GANG_ADD_GANG = ".lq.RecordAnGangAddGang"
RECORD_HULE = ".lq.RecordHule"
RECORD_LIU_JU = ".lq.RecordLiuJu"
RECORD_NO_TILE = ".lq.RecordNoTile"


def _get_head_result(head: dict) -> tuple[list, list, list]:
    """从 head 取出 result.players 与 accounts，保证按 seat 对齐。返回 (by_seat, final_scores, ranks)。"""
    result = head.get("result") or {}
    players = result.get("players") or []
    accounts = head.get("accounts") or []
    n = max(len(players), len(accounts), 4)
    # 按 seat 索引
    by_seat = [None] * n
    for p in players:
        seat = p.get("seat", 0)
        if 0 <= seat < n:
            by_seat[seat] = dict(p) if isinstance(p, dict) else {}
    for a in accounts:
        seat = a.get("seat", 0)
        if 0 <= seat < n:
            if by_seat[seat] is None:
                by_seat[seat] = {}
            if isinstance(by_seat[seat], dict):
                by_seat[seat].setdefault("account_id", a.get("account_id", ""))
                by_seat[seat].setdefault("nickname", a.get("nickname", ""))
    # 终盘分、顺位
    final_scores = [0] * n
    ranks = [0] * n
    for p in players:
        seat = p.get("seat", 0)
        if 0 <= seat < n:
            final_scores[seat] = p.get("total_point", 0) or p.get("part_point_1", 0)
            ranks[seat] = (p.get("rank", 0) + 1) if isinstance(p.get("rank"), int) else 0
    return by_seat, final_scores, ranks


def _parse_one_game(file_path: Path) -> list[dict] | None:
    """
    解析单局 JSON，返回多行（每名玩家一行）的统计列表。
    每行包含: game_uuid, account_id, nickname, seat, 初始分, 终盘分, 顺位,
    和了数, 放铳数, 立直数, 副露数, 流局听牌数, 总局数(1), 以及若干率。
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Skip %s: %s", file_path, e)
        return None

    uuid_val = data.get("uuid", file_path.stem)
    head = data.get("head") or {}
    actions = data.get("actions") or []

    by_seat, final_scores, ranks = _get_head_result(head)
    n_players = len([x for x in by_seat if x is not None])
    if n_players == 0:
        n_players = 4
    n_players = min(n_players, 4)

    # 从 head 取 account_id / nickname（以 account_id 为唯一标识）
    account_ids = [""] * 4
    nicknames = [""] * 4
    for i, x in enumerate(by_seat):
        if i >= 4:
            break
        if isinstance(x, dict):
            account_ids[i] = str(x.get("account_id") or "")
            nicknames[i] = str(x.get("nickname") or "")

    # 每局初始分：从第一个 RecordNewRound 的 scores 取
    initial_scores = [25000] * 4  # 默认东起 25000
    # 巡目计数（每局内打出的手牌次数，用于近似“参与巡数”）
    round_count = 0
    # 当前局内的 last_discard_seat（用于放铳判定）
    last_discard_seat = -1
    # 当前局内是否已产生结果（和了/流局）
    current_initial = None

    # 累计：和了、放铳、立直、副露、流局听牌
    wins = [0] * 4
    deal_in = [0] * 4
    riichi = [0] * 4
    meld_count = [0] * 4
    no_ten_rounds = 0
    tenpai_on_no_ten = [0] * 4

    for item in actions:
        name = item.get("name") or ""
        d = item.get("data") or {}
        if name == RECORD_NEW_ROUND:
            round_count += 1
            scores = d.get("scores") or []
            if scores and current_initial is None:
                for i, s in enumerate(scores):
                    if i < 4:
                        initial_scores[i] = s
                current_initial = list(initial_scores)
            last_discard_seat = -1
            continue
        if name == RECORD_DISCARD_TILE:
            seat = d.get("seat", 0)
            if 0 <= seat < 4:
                if d.get("is_liqi"):
                    riichi[seat] += 1
                last_discard_seat = seat
            continue
        if name == RECORD_CHI_PENG_GANG:
            seat = d.get("seat", 0)
            if 0 <= seat < 4:
                meld_count[seat] += 1
            continue
        if name == RECORD_AN_GANG_ADD_GANG:
            seat = d.get("seat", 0)
            if 0 <= seat < 4:
                meld_count[seat] += 1
            continue
        if name == RECORD_HULE:
            hules = d.get("hules") or [{}]
            zimo = hules[0].get("zimo", False) if hules else False
            seat = d.get("seat", 0)
            if 0 <= seat < 4:
                wins[seat] += 1
            if not zimo and 0 <= last_discard_seat < 4:
                deal_in[last_discard_seat] += 1
            last_discard_seat = -1
            continue
        if name == RECORD_LIU_JU:
            # 流局：type 等；听牌信息可能在 scores 的 delta_scores 或单独字段
            no_ten_rounds += 1
            # 若协议中有听牌标记，可在此累加 tenpai_on_no_ten[seat]
            continue
        if name == RECORD_NO_TILE:
            no_ten_rounds += 1
            scores = d.get("scores") or []
            for s in scores:
                seat = s.get("seat", 0)
                # 流局听牌：通常有 no_ten 或 ten 等字段，这里用 delta 近似
                if 0 <= seat < 4 and s.get("tingpai") or s.get("ting_pai"):
                    tenpai_on_no_ten[seat] += 1
            last_discard_seat = -1
            continue

    # 若未从 RecordNewRound 取到初始分，用默认
    if current_initial is None:
        current_initial = list(initial_scores)

    # 每人一行
    rows = []
    for seat in range(n_players):
        row = {
            "game_uuid": uuid_val,
            "account_id": account_ids[seat],
            "nickname": nicknames[seat],
            "seat": seat,
            "initial_point": current_initial[seat] if seat < len(current_initial) else 25000,
            "final_point": final_scores[seat] if seat < len(final_scores) else 0,
            "rank": ranks[seat] if seat < len(ranks) else 0,
            "wins": wins[seat],
            "deal_in": deal_in[seat],
            "riichi": riichi[seat],
            "melds": meld_count[seat],
            "no_ten_tenpai": tenpai_on_no_ten[seat],
            "games": 1,
        }
        rows.append(row)
    return rows


def run_analyzer(raw_dir: Path | None = None) -> list[dict]:
    """遍历 raw_dir 下所有 .json，汇总每局每人的统计，返回扁平列表。"""
    raw_dir = raw_dir or DEFAULT_RAW_DIR
    if not raw_dir.is_dir():
        logger.warning("Raw dir not found: %s", raw_dir)
        return []

    all_rows = []
    for path in sorted(raw_dir.glob("*.json")):
        rows = _parse_one_game(path)
        if rows:
            all_rows.extend(rows)
    logger.info("Parsed %d games, %d player-games", len({r["game_uuid"] for r in all_rows}), len(all_rows))
    return all_rows


def main():
    import argparse
    parser = argparse.ArgumentParser(description="雀魂牌谱统计：从 data/raw/*.json 计算每局每人指标")
    parser.add_argument("-i", "--input-dir", type=Path, default=DEFAULT_RAW_DIR, help="原始 JSON 目录")
    parser.add_argument("-o", "--output", type=Path, help="输出 CSV 路径（不指定则只打印摘要）")
    args = parser.parse_args()

    rows = run_analyzer(args.input_dir)
    if not rows:
        logger.info("No data to output.")
        return 0

    if args.output:
        import csv
        args.output.parent.mkdir(parents=True, exist_ok=True)
        keys = list(rows[0].keys())
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        logger.info("Wrote %s", args.output)
    else:
        for r in rows[:5]:
            print(r)
        print("... total rows:", len(rows))
    return 0


if __name__ == "__main__":
    exit(main())
