# 知识库后续补充清单

## 一、优先级最高（先补这 4 份）

### 1. 字段口径表

建议文件名：
`docs/knowledge_base/20_field_semantics.md`

建议内容：

- `baseline_item_count` 的真实语义
- `purchase_running_seconds` 的真实语义
- `runtime_window_start_time` 的真实语义
- `last_limit_time` 的真实语义
- `last_account_end_time` 的真实语义
- `updated_at` 的真实语义
- `round_status` 的真实语义
- 每个字段分别说明：
  1）谁是真源
  2）谁会写它
  3）谁只读它
  4）哪些链路容易把它写坏

补这份的原因：
最近很多 BUG 本质都是字段语义、运行态和 canonical 真源边界没被一眼看清。

### 2. 实机验收清单

建议文件名：
`docs/knowledge_base/21_acceptance_checklist.md`

建议内容：

- 按场景列短清单：
- 抢购循环验收
- 上架流程验收
- 换区 / 换号验收
- F12 暂停 / 恢复验收
- 网页本机编辑验收
- 双机同步验收
- Tailscale 验收
- 购买确认点击时序验收

补这份的原因：
以后每次收尾，不用再临时回忆“该验什么”。

### 3. 故障排查入口页

建议文件名：
`docs/knowledge_base/22_troubleshooting_index.md`

建议内容：

- 按“现象 -> 先查哪里”写：
- 启动后数据被重置 -> 查 `main.py` 启动清理入口
- F12 后数据回弹 -> 查恢复回灌链路
- 悬浮窗时间不对 -> 查 `overlay` 显示口径 / `purchase` 退出链路
- 2号电脑不同步 -> 查 canonical 主库 / web sync 配置 / Tailscale
- 网页打不开 -> 查 `web_bind_host` / `8391` / Tailscale 地址
- 2号电脑昵称识别不到 -> 查 `nickname_template_dir` / 模板目录 / 识别区域

补这份的原因：
对我和 Codex 都更省排查时间。

### 4. 本机差异总表

建议文件名：
`docs/knowledge_base/23_machine_diff_matrix.md`

建议内容：

- 分别列：
- 1号电脑当前本机配置
- 2号电脑当前本机配置
- `local_switch_account_config.json` 差异
- `local_web_sync_config.json` 差异
- 昵称模板目录差异
- 执行位 / 昵称 / 区服差异
- Tailscale 访问方式差异

补这份的原因：
后面重装、迁移、复制脚本到另一台电脑时，不容易漏关键差异。
