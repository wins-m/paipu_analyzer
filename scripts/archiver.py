# scripts/archiver.py
"""
Phase 4: 选手归档与报告。
对 10–30 场对局中的所有选手按 account_id 聚合，计算加权平均指标，生成 summary_report.xlsx。
"""
import logging
from pathlib import Path

import pandas as pd

from .analyzer import run_analyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def _aggregate_by_account(rows: list[dict]) -> pd.DataFrame:
    """
    按 account_id 聚合：同一选手多局合并，计算加权平均/总和。
    优先以 account_id 为唯一标识；无 account_id 时用 nickname 辅助（可能重复）。
    """
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # 用 account_id 聚合；空则用 nickname
    group_key = "account_id"
    if df["account_id"].fillna("").astype(str).str.strip().eq("").all():
        group_key = "nickname"
    # 保留一个 nickname 示例
    out = df.groupby(group_key, dropna=False).agg(
        games=("games", "sum"),
        wins=("wins", "sum"),
        deal_in=("deal_in", "sum"),
        riichi=("riichi", "sum"),
        melds=("melds", "sum"),
        no_ten_tenpai=("no_ten_tenpai", "sum"),
        initial_point=("initial_point", "mean"),
        final_point=("final_point", "mean"),
        rank_avg=("rank", "mean"),
    ).reset_index()
    # 昵称取第一个
    nick = df.groupby(group_key, dropna=False)["nickname"].first().reset_index()
    nick.columns = [group_key, "nickname"]
    out = out.merge(nick, on=group_key, how="left")

    # 加权平均率：总放铳数/总局数、总和了数/总局数 等
    out["win_rate"] = (out["wins"] / out["games"]).round(4)
    out["deal_in_rate"] = (out["deal_in"] / out["games"]).round(4)
    out["riichi_rate"] = (out["riichi"] / out["games"]).round(4)
    out["meld_rate"] = (out["melds"] / out["games"]).round(4)
    out["rank_avg"] = out["rank_avg"].round(2)
    return out


def run_archiver(
    raw_dir: Path | None = None,
    output_dir: Path | None = None,
    output_name: str = "summary_report.xlsx",
) -> Path:
    """从 raw 目录解析牌谱 → 统计 → 按选手聚合 → 写出 Excel。返回输出文件路径。"""
    raw_dir = raw_dir or DEFAULT_RAW_DIR
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / output_name

    rows = run_analyzer(raw_dir)
    if not rows:
        logger.warning("No records to archive.")
        out_path = output_dir / output_name
        pd.DataFrame().to_excel(out_path, index=False, engine="openpyxl")
        return out_path

    agg = _aggregate_by_account(rows)
    agg.to_excel(out_path, index=False, engine="openpyxl")
    logger.info("Wrote %s (%d players)", out_path, len(agg))
    return out_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="雀魂牌谱归档：统计并生成 summary_report.xlsx")
    parser.add_argument("-i", "--input-dir", type=Path, default=DEFAULT_RAW_DIR, help="原始 JSON 目录")
    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="报告输出目录")
    parser.add_argument("-f", "--output-name", default="summary_report.xlsx", help="输出文件名")
    args = parser.parse_args()

    run_archiver(raw_dir=args.input_dir, output_dir=args.output_dir, output_name=args.output_name)
    return 0


if __name__ == "__main__":
    exit(main())
