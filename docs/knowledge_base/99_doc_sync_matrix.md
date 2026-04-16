# 文档同步矩阵

这份文档用于回答“某类改动发生后，应该同步哪些文档”。它是知识库维护索引，不代替 `AGENTS.md` 或专题正文。

| 变更类型 | 需要同步的文档 |
| --- | --- |
| 启动入口 / 验收入口变化 | `AGENTS.md`；[04_operations_and_acceptance.md](04_operations_and_acceptance.md) |
| 数据语义 / 冷却规则 / 字段含义变化 | [03_runtime_and_data.md](03_runtime_and_data.md)；必要时 [../current_baseline.md](../current_baseline.md) |
| 执行位调度 / 切区换号 / 失败治理变化 | [05_feature_switch_and_dispatch.md](05_feature_switch_and_dispatch.md) |
| 上架 / 余额 / 悬浮窗规则变化 | [06_feature_listing_balance_overlay.md](06_feature_listing_balance_overlay.md)；若影响硬规则，再同步 `AGENTS.md` |
| 网页 / 远端镜像 / 公网快照边界变化 | [07_feature_web_and_sync.md](07_feature_web_and_sync.md)；[../web_and_sync.md](../web_and_sync.md)；若影响红线，再同步 `AGENTS.md` |
| 本机配置 / 模板资源 / live 目录变化 | [08_local_config_and_assets.md](08_local_config_and_assets.md)；[../local_config.md](../local_config.md) |
| 主线新增已合回能力 | [00_start_here.md](00_start_here.md)；[01_system_overview.md](01_system_overview.md)；[../current_baseline.md](../current_baseline.md) |

相关文档： [README.md](README.md)
