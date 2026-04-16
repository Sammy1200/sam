# 项目知识库入口

这份文档是知识库总入口，用于告诉第一次接手项目的人先读什么、各类文档分别负责什么。

## 推荐阅读顺序

第一次接手本项目，建议按下面顺序阅读：

1. [00_start_here.md](00_start_here.md)
2. [01_system_overview.md](01_system_overview.md)
3. [02_module_map.md](02_module_map.md)
4. [03_runtime_and_data.md](03_runtime_and_data.md)
5. [04_operations_and_acceptance.md](04_operations_and_acceptance.md)

读完上面 5 份后，再按问题类型进入专题文档：

- 执行位调度、切区、换号： [05_feature_switch_and_dispatch.md](05_feature_switch_and_dispatch.md)
- 上架、余额、悬浮窗： [06_feature_listing_balance_overlay.md](06_feature_listing_balance_overlay.md)
- 网页、本机查看、远端镜像： [07_feature_web_and_sync.md](07_feature_web_and_sync.md)
- 本机配置、模板资源、live 数据目录： [08_local_config_and_assets.md](08_local_config_and_assets.md)
- 术语统一： [90_glossary.md](90_glossary.md)
- 文档维护索引： [99_doc_sync_matrix.md](99_doc_sync_matrix.md)

## 三类文档的分工

- `AGENTS.md`
  负责开工前必读规则、正式运行/验收入口、红线、高敏感区、Git 与本机真实配置规则，以及“接下来该读哪几份知识库文档”的导航。
- `docs/knowledge_base/`
  负责解释当前系统是什么、怎么运行、模块怎么协作、数据怎么流动、当前边界在哪里、常见误解和排错入口是什么。
- `docs/thread_history.md`
  只负责历史归档，记录哪个线程做了什么、是否已合回主线、是否验收，不承担当前系统说明书职责。

## 使用原则

- 知识库以“当前主线真实口径”为准，优先交叉核对 `AGENTS.md`、现有专题文档和当前代码。
- 如果历史文档与当前代码有差异，以当前实现和当前规则为准。
- 知识库不是线程流水账，不按分支推进过程组织。

下一份建议阅读： [00_start_here.md](00_start_here.md)
