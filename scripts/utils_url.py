# scripts/utils_url.py
"""
Phase 1: 从雀魂牌谱 URL 中提取主 UUID。
忽略视角后缀（如 _a123...），只保留下划线前的 UUID 部分。
"""
import re
from urllib.parse import urlparse, parse_qs


# 牌谱 URL 示例: https://game.maj-soul.com/1/?paipu=UUID_a123...
# 或: https://game.maj-soul.com/1/?paipu=UUID
PAIPU_PARAM = "paipu"


def extract_uuid_from_url(url: str) -> str | None:
    """
    从牌谱链接中提取主 UUID（下划线前的部分）。
    - 输入: https://game.maj-soul.com/1/?paipu=xxxx-xxxx-xxxx_a123
    - 输出: xxxx-xxxx-xxxx
    """
    if not url or not url.strip():
        return None
    url = url.strip()
    # 支持直接传入 UUID（可能带后缀）
    if not url.startswith("http"):
        return _uuid_before_underscore(url)
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if PAIPU_PARAM not in qs:
        return None
    value = qs[PAIPU_PARAM][0]
    return _uuid_before_underscore(value)


def _uuid_before_underscore(s: str) -> str:
    """只保留下划线之前的部分，忽略 _a123... 等视角后缀。"""
    if "_" in s:
        return s.split("_", 1)[0].strip()
    return s.strip()


def extract_uuids_from_urls(urls: list[str]) -> list[str]:
    """从多个 URL 中提取 UUID，去重并保持顺序。"""
    seen = set()
    result = []
    for u in urls:
        uuid_val = extract_uuid_from_url(u)
        if uuid_val and uuid_val not in seen:
            seen.add(uuid_val)
            result.append(uuid_val)
    return result
