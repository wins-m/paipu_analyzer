# protocols

本目录用于放置雀魂协议相关资源。

- **Python 协议代码**：本项目通过依赖 `mahjong-soul-api`（即 `ms` 包）使用其已编译的 `ms.protocol_pb2`，无需在本仓库内执行 `protoc`。
- **Proto 定义参考**：完整 .proto 定义可参考 [amae-koromo-scripts](https://github.com/SAPikachu/amae-koromo-scripts) 中的 `majsoulPb.proto.json` 或 [MahjongRepository/mahjong_soul_api](https://github.com/MahjongRepository/mahjong_soul_api) 的 `ms` 模块。

若需自行从 .proto 生成 Python 代码，请安装 `protoc` 并：

```bash
protoc --python_out=./generated your.proto
```

当前实现直接使用 `mahjong-soul-api` 的协议层，无需额外生成步骤。
