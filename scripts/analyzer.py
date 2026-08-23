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
RECORD_DEAL_TILE = ".lq.RecordDealTile"
RECORD_CHI_PENG_GANG = ".lq.RecordChiPengGang"
RECORD_AN_GANG_ADD_GANG = ".lq.RecordAnGangAddGang"
RECORD_HULE = ".lq.RecordHule"
RECORD_LIU_JU = ".lq.RecordLiuJu"
RECORD_NO_TILE = ".lq.RecordNoTile"


def _seat_to_index(seat: Any) -> int | None:
    """
    雀魂协议 seat 为 1-based：1=东、2=南、3=西、4=北。
    转为 0-based 下标：0=东、1=南、2=西、3=北。
    """
    if seat is None:
        return None
    try:
        s = int(seat)
    except (TypeError, ValueError):
        return None
    if 1 <= s <= 4:
        return s - 1
    if 0 <= s <= 3:
        return s  # 兼容已为 0-based 的旧数据
    return None


def _get_head_result(head: dict) -> tuple[list, list, list, list]:
    """
    从 head 取出 result.players 与 accounts，保证按 seat 对齐。
    与 amae-koromo 一致：顺位按终盘分从高到低 1～4，缺 seat 时按数组下标当作 seat。
    返回 (by_seat, final_scores, ranks, result_order_to_seat)。
    result_order_to_seat[i] = result.players[i] 的 0-based 座次（东0南1西2北3），RecordHule 的 seat/delta_scores 为 result.players 数组下标。
    """
    result = head.get("result") or {}
    players = result.get("players") or []
    accounts = head.get("accounts") or []
    n = max(len(players), len(accounts), 4)
    n = min(n, 4)
    # 协议 seat 为 1-based，转为 0-based；为没有 seat 的 player 分配剩余座次
    used_seats = set()
    player_seat_point = []  # (seat_0based, total_point, p)
    for p in players:
        if not isinstance(p, dict):
            continue
        pt = p.get("total_point", 0) or p.get("part_point_1", 0)
        seat = _seat_to_index(p.get("seat"))
        if seat is not None:
            used_seats.add(seat)
            player_seat_point.append((seat, pt, p))
        else:
            player_seat_point.append((-1, pt, p))  # 无 seat，稍后分配
    free_seats = [s for s in range(n) if s not in used_seats]
    for i, (seat, pt, p) in enumerate(player_seat_point):
        if seat == -1 and free_seats:
            player_seat_point[i] = (free_seats.pop(0), pt, p)

    by_seat = [None] * n
    for seat, _pt, p in player_seat_point:
        if 0 <= seat < n:
            by_seat[seat] = dict(p)
            by_seat[seat]["seat"] = seat
    # accounts：协议 seat 1-based → 0-based；缺 seat 的分配剩余座次
    used_acc_seats = set()
    acc_list = []  # (seat_0based, account_dict)
    for a in accounts:
        if not isinstance(a, dict):
            continue
        seat = _seat_to_index(a.get("seat"))
        if seat is None:
            seat = -1
        if 0 <= seat < n:
            used_acc_seats.add(seat)
            acc_list.append((seat, a))
        else:
            acc_list.append((-1, a))
    free_acc_seats = [s for s in range(n) if s not in used_acc_seats]
    for i, (seat, a) in enumerate(acc_list):
        if seat == -1 and free_acc_seats:
            acc_list[i] = (free_acc_seats.pop(0), a)
    for seat, a in acc_list:
        if 0 <= seat < n:
            if by_seat[seat] is None:
                by_seat[seat] = {}
            if isinstance(by_seat[seat], dict):
                by_seat[seat].setdefault("account_id", a.get("account_id", ""))
                by_seat[seat].setdefault("nickname", a.get("nickname", ""))

    # 终盘分：按 seat 填
    final_scores = [0] * n
    for seat, pt, _p in player_seat_point:
        final_scores[seat] = pt

    # 顺位：按终盘分从高到低 1～4（与 amae-koromo 一致）
    rank_by_seat = {}
    sorted_seats = sorted(range(n), key=lambda s: final_scores[s], reverse=True)
    for rank_one_based, seat in enumerate(sorted_seats, start=1):
        rank_by_seat[seat] = rank_one_based
    ranks = [rank_by_seat.get(s, 0) for s in range(n)]
    result_order_to_seat = [player_seat_point[i][0] for i in range(len(player_seat_point))]
    while len(result_order_to_seat) < 4:
        result_order_to_seat.append(None)
    return by_seat, final_scores, ranks, result_order_to_seat[:4]


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

    by_seat, final_scores, ranks, result_order_to_seat = _get_head_result(head)
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
    # 立直可能出现在 RecordDiscardTile（有 seat）或下一手 RecordDealTile.liqi.seat，避免同一次立直计两次
    just_counted_riichi = False
    last_riichi_seat = -1  # 最近一次计入立直时的座次，用于立直放铳时回退
    # 当前行动者（0-based），用于推断无 seat 的 Record：协议中部分打出/摸牌无 seat，按轮转东→南→西→北→东
    current_seat = 0
    # 上一手打出是否为立直（含摸牌立直后当即打出）：立直放铳时该次立直不计入
    last_discard_was_riichi = False

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
            just_counted_riichi = False
            last_discard_was_riichi = False
            last_riichi_seat = -1
            # 协议中第一个打出常无 seat，为北家(3)；北→东→南→西，故新局后当前行动者=北家
            current_seat = 3
            continue
        if name == RECORD_DISCARD_TILE:
            idx = _seat_to_index(d.get("seat"))
            if idx is None:
                idx = current_seat  # 无 seat 时按轮转视为当前行动者（多为北家）
            if 0 <= idx < 4:
                is_liqi = d.get("is_liqi")
                # 打牌立直 或 摸牌立直后当即打出（上一事件 DealTile.liqi 且本手打出者=立直者）
                last_discard_was_riichi = bool(is_liqi) or (just_counted_riichi and idx == last_riichi_seat)
                if is_liqi:
                    riichi[idx] += 1
                    just_counted_riichi = True
                    last_riichi_seat = idx
                else:
                    just_counted_riichi = False
                    last_riichi_seat = -1
                last_discard_seat = idx
            else:
                last_discard_was_riichi = False
            current_seat = (idx + 1) % 4 if idx is not None else (current_seat + 1) % 4
            continue
        if name == RECORD_DEAL_TILE:
            raw_seat = d.get("seat")
            if raw_seat is not None:
                idx = _seat_to_index(raw_seat)
                if idx is not None:
                    current_seat = idx  # 有 seat 时同步轮转
            if not just_counted_riichi:
                liqi = d.get("liqi")
                if isinstance(liqi, dict) and "seat" in liqi:
                    idx = _seat_to_index(liqi["seat"])
                    if idx is not None:
                        riichi[idx] += 1
                        last_riichi_seat = idx
            just_counted_riichi = False
            continue
        if name == RECORD_CHI_PENG_GANG:
            # 副露 seat 为 1-based（1=东、2=南、3=西、4=北）；协议常省略北家则送 None，归为 index 3
            raw_seat = d.get("seat")
            idx = _seat_to_index(raw_seat) if raw_seat is not None else 3
            if idx is not None and 0 <= idx < 4:
                meld_count[idx] += 1
            continue
        if name == RECORD_AN_GANG_ADD_GANG:
            raw_seat = d.get("seat")
            idx = _seat_to_index(raw_seat) if raw_seat is not None else 3
            if idx is not None and 0 <= idx < 4:
                meld_count[idx] += 1
            continue
        if name == RECORD_HULE:
            # 和了者仅从 delta_scores 判定（与 result.players 顺序一致），避免 hule.seat 与 by_seat 错位
            hules = d.get("hules") or []
            delta_scores = d.get("delta_scores") or []
            for i in range(min(4, len(delta_scores))):
                if delta_scores[i] > 0 and i < len(result_order_to_seat) and result_order_to_seat[i] is not None:
                    seat = result_order_to_seat[i]
                    if 0 <= seat < 4:
                        wins[seat] += 1
            zimo_any = any(isinstance(h, dict) and h.get("zimo") for h in (hules or []))
            if not zimo_any and last_discard_seat is not None and 0 <= last_discard_seat < 4:
                deal_in[last_discard_seat] += 1
                # 立直放铳：该次立直不计入，从放铳者立直数回退 1
                if last_discard_was_riichi:
                    riichi[last_discard_seat] = max(0, riichi[last_discard_seat] - 1)
            last_discard_seat = -1
            last_discard_was_riichi = False
            continue
        if name == RECORD_LIU_JU:
            no_ten_rounds += 1
            continue
        if name == RECORD_NO_TILE:
            # 流局听牌：data.players 按 seat 顺序，每项有 tingpai 表示该席听牌（与 amae-koromo 协议一致）
            no_ten_rounds += 1
            for seat, p in enumerate(d.get("players") or []):
                if 0 <= seat < 4 and isinstance(p, dict) and p.get("tingpai"):
                    tenpai_on_no_ten[seat] += 1
            last_discard_seat = -1
            last_discard_was_riichi = False
            continue

    # 若未从 RecordNewRound 取到初始分，用默认
    if current_initial is None:
        current_initial = list(initial_scores)

    # 每人一行：按 seat 0=东、1=南、2=西、3=北 顺序输出，与 by_seat/wins 下标一致
    rows = []
    n_out = min(4, max(n_players, 4))
    for seat in range(n_out):
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
