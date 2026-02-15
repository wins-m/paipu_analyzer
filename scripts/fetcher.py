# scripts/fetcher.py
"""
Phase 2: 数据下载器。
模拟雀魂客户端登录，调用 fetchGameRecord 获取牌谱，将 Protobuf 转为 JSON 并保存到 data/raw/。
依赖 mahjong_soul_api (ms) 的网络层，复用其 WebSocket 握手与认证逻辑。
"""
import asyncio
import hashlib
import hmac
import json
import logging
import random
import uuid
from pathlib import Path

import aiohttp
from google.protobuf.json_format import MessageToDict
import ms.protocol_pb2 as pb
from ms.base import MSRPCChannel
from ms.rpc import Lobby

from .utils_url import extract_uuid_from_url, extract_uuids_from_urls

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

MS_HOST = "https://game.maj-soul.com"
DEFAULT_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


class FetcherError(Exception):
    """牌谱获取相关错误。"""
    pass


class FetcherLoginError(FetcherError):
    """登录失败。"""
    pass


class FetcherRecordError(FetcherError):
    """单条牌谱获取失败（如链接失效）。"""
    def __init__(self, game_uuid: str, code: int, message: str = ""):
        self.game_uuid = game_uuid
        self.code = code
        self.message = message
        super().__init__(f"record {game_uuid}: code={code} {message}".strip())


def _extract_url_from_entry(entry) -> str | None:
    if isinstance(entry, dict):
        return entry.get("url") or entry.get("uri")
    return None


def _url_from_gateway_entry(entry) -> str | None:
    """从 gateways 列表的一项得到用于请求 server 列表的 base URL。"""
    if isinstance(entry, dict):
        return _extract_url_from_entry(entry)
    if isinstance(entry, str):
        if entry.startswith("http"):
            return entry
        # hostname 形式，当作 HTTPS base
        return "https://" + entry
    return None


def _get_region_url_from_config(config: dict) -> tuple[str | None, str | None]:
    """
    从 config 解析 gateway。返回 (query_url, direct_wss_endpoint)。
    - 若为 HTTP 查询地址：返回 (url, None)，调用方 GET url?service=ws-gateway... 取 servers。
    - 若为直接 WSS 地址（如 gateways 为 hostname 列表）：返回 (None, "wss://host/gateway")。
    """
    # 1) 尝试顶层或 ip 下的直接 url
    for key in ("url", "gateway_url", "region_url", "ws_url"):
        u = config.get(key)
        if isinstance(u, str) and u.startswith("http"):
            return (u, None)
    ip_list = config.get("ip") or []
    if not ip_list:
        raise FetcherError("config has no 'ip'. Top-level keys: %s" % list(config.keys()))
    first_ip = ip_list[0] or {}
    if not isinstance(first_ip, dict):
        raise FetcherError("config ip[0] is not a dict")
    # 2) 尝试 ip[0] 下多种可能的 key（雀魂新版用 gateways 替代 region_urls）
    for key in ("gateways", "region_urls", "region_servers", "servers", "urls"):
        region_urls = first_ip.get(key)
        if not region_urls:
            continue
        if isinstance(region_urls, str) and region_urls.startswith("http"):
            return (region_urls, None)
        if isinstance(region_urls, list):
            for idx in (1, 0):
                if len(region_urls) > idx:
                    entry = region_urls[idx]
                    if isinstance(entry, str):
                        if entry.startswith("wss://"):
                            return (None, entry)
                        if entry.startswith("http"):
                            return (entry, None)
                        # 纯 hostname：直接当 WSS 用，避免卡在 HTTP 查询
                        return (None, f"wss://{entry.rstrip('/')}/gateway")
                    url = _url_from_gateway_entry(entry)
                    if url:
                        if url.startswith("wss://"):
                            return (None, url)
                        return (url, None)
            if region_urls:
                entry = region_urls[0]
                if isinstance(entry, str):
                    if entry.startswith("wss://"):
                        return (None, entry)
                    if entry.startswith("http"):
                        return (entry, None)
                    return (None, f"wss://{entry.rstrip('/')}/gateway")
                url = _url_from_gateway_entry(entry)
                if url:
                    if url.startswith("wss://"):
                        return (None, url)
                    return (url, None)
        elif isinstance(region_urls, dict):
            for k in ("1", "0", "cn", "main"):
                if k in region_urls:
                    url = _extract_url_from_entry(region_urls[k])
                    if url:
                        return (url, None)
            for v in region_urls.values():
                url = _extract_url_from_entry(v)
                if url:
                    return (url, None)
    # 3) ip[0] 下直接 url
    for key in ("url", "region_url", "gateway_url"):
        u = first_ip.get(key)
        if isinstance(u, str) and u.startswith("http"):
            return (u, None)
    raise FetcherError(
        "Could not find region/gateway url. config top-level keys: %s; ip[0] keys: %s"
        % (list(config.keys()), list(first_ip.keys()))
    )


# HTTP 请求超时，避免卡死
_NETWORK_TIMEOUT = aiohttp.ClientTimeout(total=25, connect=10)
_GATEWAY_QUERY_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=8)


def _https_url_to_wss_endpoint(https_url: str) -> str:
    """将 gateway 的 HTTPS 地址转为 WSS 地址，如 https://route-3.maj-soul.com:8443 -> wss://route-3.maj-soul.com:8443/gateway"""
    from urllib.parse import urlparse
    p = urlparse(https_url)
    host = p.hostname or p.netloc.split(":")[0]
    port = p.port
    if port is None or port in (443, 80):
        return f"wss://{host}/gateway"
    return f"wss://{host}:{port}/gateway"


async def _get_endpoint_and_version() -> tuple[str, str]:
    """获取 WebSocket gateway 与 version_to_force。返回 (endpoint, version_to_force)。"""
    async with aiohttp.ClientSession(timeout=_NETWORK_TIMEOUT) as session:
        logger.info("Fetching version...")
        async with session.get(f"{MS_HOST}/1/version.json") as res:
            ver = await res.json()
            version_str = ver.get("version", "0.0.0")
        version_to_force = version_str.replace(".w", "")

        logger.info("Fetching config...")
        async with session.get(f"{MS_HOST}/1/v{version_str}/config.json") as res:
            config = await res.json()
        url, direct_wss = _get_region_url_from_config(config)

        if direct_wss:
            endpoint = direct_wss
            logger.info("Using gateway: %s", endpoint)
        else:
            logger.info("Resolving gateway list from %s...", url[:60] + "..." if len(url) > 60 else url)
            try:
                async with aiohttp.ClientSession(timeout=_GATEWAY_QUERY_TIMEOUT) as gw_session:
                    async with gw_session.get(url + "?service=ws-gateway&protocol=ws&ssl=true") as res:
                        servers = await res.json()
                if "servers" not in servers:
                    raise FetcherError("Cannot get gateway servers")
                server = random.choice(servers["servers"])
                endpoint = f"wss://{server}/gateway"
            except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as e:
                logger.warning("Gateway list request failed (%s), using URL as WSS endpoint", e)
                endpoint = _https_url_to_wss_endpoint(url)
            logger.info("Connecting to gateway: %s", endpoint)
    return endpoint, version_to_force


def _pb_to_dict(msg) -> dict:
    """Protobuf Message 转可 JSON 序列化的 dict。"""
    return MessageToDict(
        msg,
        preserving_proto_field_name=True,
        use_integers_for_enums=True,
    )


def _decode_detail_records(record_data: bytes) -> list[dict]:
    """将 record.data 解析为 GameDetailRecords，再把每条 action/record 解码为 dict 列表。"""
    wrapper = pb.Wrapper()
    wrapper.ParseFromString(record_data)
    details = pb.GameDetailRecords()
    details.ParseFromString(wrapper.data)

    actions_out = []
    # 新格式: details.actions[*].result 为每条 Wrapper
    if getattr(details, "actions", None) and len(details.actions) > 0:
        for act in details.actions:
            if not act.result:
                continue
            wr = pb.Wrapper()
            wr.ParseFromString(act.result)
            type_name = wr.name  # e.g. .lq.RecordNewRound
            msg_type = getattr(pb, wr.name.replace(".lq.", ""), None)
            if msg_type is None:
                actions_out.append({"name": type_name, "data_hex": wr.data.hex()})
                continue
            msg = msg_type()
            msg.ParseFromString(wr.data)
            actions_out.append({"name": type_name, "data": _pb_to_dict(msg)})
    # 旧格式: details.records 为多条 Wrapper
    elif getattr(details, "records", None) and len(details.records) > 0:
        for rec in details.records:
            wr = pb.Wrapper()
            wr.ParseFromString(rec)
            type_name = wr.name
            msg_type = getattr(pb, wr.name.replace(".lq.", ""), None)
            if msg_type is None:
                actions_out.append({"name": type_name, "data_hex": wr.data.hex()})
                continue
            msg = msg_type()
            msg.ParseFromString(wr.data)
            actions_out.append({"name": type_name, "data": _pb_to_dict(msg)})
    return actions_out


async def fetch_one(
    lobby: Lobby,
    version_to_force: str,
    game_uuid: str,
    out_dir: Path,
) -> Path | None:
    """
    拉取一条牌谱并保存为 JSON。成功返回输出文件路径，失败返回 None 并打 log。
    """
    req = pb.ReqGameRecord()
    req.game_uuid = game_uuid
    req.client_version_string = f"web-{version_to_force}"

    try:
        if hasattr(lobby, "fetch_game_record"):
            res = await lobby.fetch_game_record(req)
        else:
            res = await lobby.call_method("fetchGameRecord", req)
    except Exception as e:
        logger.warning("fetch_game_record failed for %s: %s", game_uuid, e)
        return None

    if res.error and res.error.code:
        # 已失效的牌谱（如超过约 30 天未存盘）会返回错误码，跳过并记录
        logger.warning("Record unavailable or expired: uuid=%s code=%s", game_uuid, res.error.code)
        return None

    head_dict = _pb_to_dict(res.head)
    actions = _decode_detail_records(res.data)
    payload = {
        "uuid": game_uuid,
        "head": head_dict,
        "actions": actions,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{game_uuid}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("Saved: %s", out_path)
    return out_path


async def run_fetcher(
    uuid_list: list[str],
    username: str,
    password: str,
    raw_dir: Path | None = None,
) -> list[Path]:
    """
    连接 → 登录 → 按 UUID 列表批量拉取牌谱并保存到 raw_dir。
    返回成功保存的文件路径列表。已失效的链接会跳过并记录 Log。
    """
    raw_dir = raw_dir or DEFAULT_RAW_DIR
    endpoint, version_to_force = await _get_endpoint_and_version()
    channel = MSRPCChannel(endpoint)
    logger.info("Connecting WebSocket...")
    try:
        await asyncio.wait_for(channel.connect(MS_HOST), timeout=20.0)
    except asyncio.TimeoutError:
        await channel.close()
        raise FetcherError("WebSocket connection timed out (20s)")
    lobby = Lobby(channel)

    logger.info("Logging in...")
    req = pb.ReqLogin()
    req.account = username
    req.password = hmac.new(b"lailai", password.encode(), hashlib.sha256).hexdigest()
    req.device.is_browser = True
    req.random_key = str(uuid.uuid1())
    req.gen_access_token = True
    req.client_version_string = f"web-{version_to_force}"
    req.currency_platforms.append(2)

    login_res = await lobby.login(req)
    if not login_res.access_token:
        await channel.close()
        raise FetcherLoginError("Login failed (no access_token)")

    saved = []
    for game_uuid in uuid_list:
        path = await fetch_one(lobby, version_to_force, game_uuid, raw_dir)
        if path is not None:
            saved.append(path)
        await asyncio.sleep(0.3)  # 避免请求过快

    await channel.close()
    return saved


def main():
    import argparse
    parser = argparse.ArgumentParser(description="雀魂牌谱下载器：从 URL 或 UUID 列表下载牌谱到 data/raw/")
    parser.add_argument("inputs", nargs="+", help="牌谱 URL 或 UUID（可混用）")
    parser.add_argument("-u", "--username", required=True, help="雀魂账号（仅国服支持账号密码）")
    parser.add_argument("-p", "--password", required=True, help="雀魂密码")
    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_RAW_DIR, help="原始 JSON 输出目录")
    args = parser.parse_args()

    uuids = extract_uuids_from_urls(args.inputs)
    if not uuids:
        logger.error("未解析到任何有效 UUID")
        return 1

    logger.info("Resolved %d UUID(s), start fetching...", len(uuids))
    try:
        paths = asyncio.run(run_fetcher(uuids, args.username, args.password, args.output_dir))
    except FetcherError as e:
        logger.error("%s", e)
        return 1
    logger.info("Done. Saved %d record(s) to %s", len(paths), args.output_dir)
    return 0


if __name__ == "__main__":
    exit(main())
