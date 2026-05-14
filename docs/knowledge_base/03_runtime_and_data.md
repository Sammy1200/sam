# 运行态与数据语义

这份文档用于统一数据口径。第一次接手时，很多误解都来自“看到了字段，但不知道它是真值、派生值还是快照值”。

## canonical SQLite 的角色

canonical SQLite 是当前系统的唯一真实数据源。

当前有两份本机 canonical SQLite：

- 石头库：`C:\py666\account_stats.sqlite3`
- 饰品库：`C:\py666\accessory_account_stats.sqlite3`

两份库不共享同一个 SQLite 文件。库存、余额/金币、抢购数、上架数等模式专属数据继续按库隔离；`账号状态`、`可运行时间`、`冷却剩余时间` 是账号通用数据，任意一边修改后必须同步到另一边。

通用数据对应的底层字段是：

- `round_status`
- `purchase_running_seconds`
- `runtime_window_start_time`
- `last_limit_time`

当前最核心的 canonical 表是：

- 表名：`account_stats`
- 主键：`nickname`

它负责承载当前主线认可的账号事实，包括：

- 道具库存基线
- 石头模式不可交易库存、可交易库存和最早解锁时间
- 当前执行位
- 当前轮次成功/失败/上架计数
- 当前余额
- 运行时间相关字段
- 账号状态
- 时间锚点字段

网页、悬浮窗、远端镜像都可以引用它，但不能替代它。

## 石头道具 72 小时不可交易库存

石头道具库存第一阶段已经完成数据模型与核心入库口径，第二阶段已经完成网页展示与手动修改口径，待统一实机验收。石头库中 `baseline_item_count` 继续作为兼容总库存字段存在，同时新增：

- `locked_item_count`：不可交易数量
- `tradable_item_count`：可交易数量
- `next_tradable_at`：当前账号最早 pending 批次到期时间，可为空

石头模式下固定满足：

- `baseline_item_count = locked_item_count + tradable_item_count`
- 旧记录迁移时，原 `baseline_item_count` 全部进入 `tradable_item_count`
- 旧记录的 `locked_item_count` 初始化为 `0`
- 旧库存不生成 pending 批次
- 新抢购成功的石头进入 `locked_item_count`，同时生成 72 小时 pending 批次
- 到期结转时，pending 批次从 `pending` 变为 `matured`，库存从不可交易转入可交易，总库存不变
- 上架成功只能扣 `tradable_item_count`，不得用 `locked_item_count` 抵扣

pending 批次表为 `stone_item_unlock_batches`，核心字段包括：

- `nickname`
- `quantity`
- `acquired_at`
- `tradable_at`
- `status`：`pending` / `matured` / `cancelled`
- `created_at`
- `updated_at`

网页查看页在石头库下按“不可交易 + 可交易 = 总库存”展示，例如 `150 + 200 = 350`：

- 不可交易数量对应 `locked_item_count`，网页显示为红色，可手动修改
- 可交易数量对应 `tradable_item_count`，网页显示为绿色，可手动修改
- 总库存对应 `baseline_item_count`，只读展示，保存时由 `locked_item_count + tradable_item_count` 自动计算
- 手动调大不可交易数量时，只给新增部分生成 72 小时 `pending` 批次
- 手动调小不可交易数量时，按 `tradable_at` 最近到期优先把对应数量的 `pending` 批次改为 `cancelled`
- 如果 pending 批次数量不足以作废，本次网页保存失败，不允许制造负库存或静默改坏数据

饰品模式不启用这套拆分逻辑。饰品库继续使用旧库存口径，饰品库存仍按 `baseline_item_count` 理解。

## 为什么昵称是唯一键

当前代码里 `account_stats` 以 `nickname TEXT PRIMARY KEY` 建表。执行位虽然重要，但只是：

- 调度入口
- 启动器选区提示
- 兼容读取和建档补位的辅助信息

它不是 canonical 的唯一键。原因是：

- 执行位会在调度链路中轮换
- 同一执行位可能先出现种子记录，再映射到真实昵称
- 真正被业务和网页共同识别的账号身份仍是昵称

所以“执行位可变，昵称主键不变”是当前系统基本语义。

## 执行位数量

默认执行位数量仍是 `1-8`。如果真实本机 `local_switch_account_config.json` 显式声明 `execution_slot_count` 以及对应的大区索引、昵称模板、下一执行位映射和跨账号边界，脚本会按该本机配置扩展执行位范围，例如 4号电脑可使用 `1-9`。

临时号不写入 canonical `account_stats`，网页账号列表也不再追加展示临时号辅助快照。

## `updated_at` 与 `last_account_end_time` 的区别

这两个字段经常被混用，但它们不是一回事。

### `updated_at`

`updated_at` 表示这条 canonical 记录最近一次被写入或刷新时间。常见来源包括：

- 网页最小修改写回
- 轻量落库
- 最终写回
- 暂停 / 恢复快照
- 账号状态变化后的事件快照同步

它反映“这条记录最近什么时候被系统改过”。

### `last_account_end_time`

`last_account_end_time` 表示当前账号最近一次完成本轮并结束账号流程的时间锚点。它更接近“最后下号 / 本轮结束时间”。

它不会在每次轻量更新时都改，而是在最终写回等结束阶段更重要。

### 不要怎么理解

- 不要把 `updated_at` 当成“最后下号时间”
- 不要把 `last_account_end_time` 当成“最近任何字段改动时间”

## 2 小时 40 分与 24 小时窗口规则

### 2 小时 40 分

当前代码常量 `ACCOUNT_MAX_PURCHASE_SECONDS` 等于 2 小时 40 分。

它的语义是：

- 只统计真正抢购循环活跃态
- 进入抢购循环前会初始化或恢复运行窗口
- 暂停、上架、冷却等待等不应被错误计入活跃抢购时间
- 达到阈值时，会记录账号达到上限的时刻，并进入 `抢购时长已到` 相关收尾

### 24 小时窗口

当前实现使用 `ACCOUNT_LIMIT_COOLDOWN_SECONDS = (24 * 60 + 1) * 60`，也就是 **24 小时 01 分**。

这有两个重要含义：

- 冷却恢复判断以这个窗口计算
- 运行窗口滚动也使用这个常量

注意：

- “24 小时 05 分”只属于历史口径，不是当前规则。
- 当前代码和当前文档统一按 24 小时 01 分理解。

## 限制类状态的统一语义

当前以下 3 个正式状态都按“限制类状态”处理：

- `余额不足`
- `账号限制`
- `抢购时长已到`

它们的共同语义是：

- 最终写库时会写入或刷新 `last_limit_time`
- `purchase_running_seconds` 会清零
- `runtime_window_start_time` 会清空
- 当前账号本轮三项计数会清零：
  - `round_purchase_success_count`
  - `round_purchase_fail_count`
  - `round_listing_success_count`
- 网页上的冷却倒计时会启动
- 网页上的“可运行时间”会立即归 `0`
- 冷却结束后会自动恢复为 `已准备`

补充时机说明：

- 正常登录界面模式中，如果当前账号命中 `余额不足`、`账号限制` 或 `抢购时长已到` 并准备换号，当前进程里的三项计数会先立刻清零：
  - `round_purchase_success_count`
  - `round_listing_success_count`
  - `round_purchase_fail_count`
- 饰品抢购模式中，如果当前账号命中 `账号限制` 或 `抢购时长已到` 并准备换号，也沿用同一套三项即时清零口径。
- 但 canonical SQLite 仍沿用最终收尾步骤统一写零，不在状态命中瞬间额外新增一轮“三项立即清库”。
- 启动页上架模式中，每个账号成功下号并确认回到启动页后，当前进程里的 `round_listing_success_count` 与兼容显示字段会立刻清零；同时，当前账号在 canonical SQLite 里的 `round_listing_success_count` 也会被清零。
- 启动页上架模式最终微信汇总使用“下号前快照”生成，不受下号后清零动作影响。
- 只要 canonical SQLite 里的 `round_status` 发生变化，系统就会立刻触发一次事件快照，同步到公网快照页。
- 启动页上架模式下按 `F12` 暂停 / 恢复时，只补最小快照，不改 `round_status`，因此不属于这条“状态变化快照”规则。

## 运行态字段、持久化字段、派生字段

### 运行态字段

运行态字段主要存在于 `state.py` 中，例如：

- `current_nickname`
- `current_execution_slot`
- `round_purchase_success_count`
- `round_listing_success_count`
- `round_purchase_fail_count`
- `round_current_balance`
- `overlay_status`
- `purchase_timer_active`

它们表示“当前进程此刻记住了什么”，不等于已经落入真源。

### 持久化字段

持久化字段主要落在 canonical `account_stats` 表中，例如：

- `baseline_item_count`
- `current_execution_slot`
- `round_purchase_success_count`
- `round_listing_success_count`
- `round_purchase_fail_count`
- `current_balance`
- `purchase_running_seconds`
- `runtime_window_start_time`
- `round_status`
- `last_limit_time`
- `last_account_end_time`
- `updated_at`

这些字段在写入 SQLite 后，才是系统正式事实。

### 派生字段

派生字段通常由 `account_view_repo.py` 在读取时计算，例如：

- `allow_purchase`
- `allow_start_time`
- `cooldown_remaining_seconds`
- `runtime_window_remaining_seconds`
- `runtime_window_remaining_text`
- `updated_at_relative`
- `inventory_quantity`

这些字段方便展示和诊断，但不是直接存储真值。

## 哪些值是真值，哪些只是快照或展示值

### 真值

下面这些值在 canonical 中是真值：

- `baseline_item_count`
- `current_balance`
- `round_status`
- `purchase_running_seconds`
- `runtime_window_start_time`
- `last_limit_time`
- `last_account_end_time`
- `updated_at`

### 辅助快照

下面这些值是辅助快照，不应替代 canonical：

- `thread6_runtime.sqlite3` 中的当前执行位与当前昵称
- `thread6_runtime.sqlite3` 中的 `临时号` 辅助快照不写入 canonical `account_stats`，也不追加到网页账号列表
- `remote_sync_mirror.sqlite3` 中的远端镜像行
- 网页上的相对时间、剩余时间、健康摘要

### 展示态

下面这些值只用于显示：

- 悬浮窗里的 `新/沿/待确认` 余额前缀
- `updated_at_relative`
- 运行窗口剩余文案
- 冷却剩余文案

## 常用状态值语义

当前主线常用状态值至少包括：

- `运行中`
  当前账号正在正式运行链路中。
- `账号限制`
  账号命中了限制类结束条件，需要进入冷却恢复窗口。
- `余额不足`
  当前有效余额低于阈值，触发本轮结束与调度。
- `抢购时长已到`
  当前账号已达到 2 小时 40 分活跃抢购上限。
- `已准备`
  正式状态值，表示账号已恢复到可重新进入流程的准备态。
- `未知异常`
  当前链路未能按已知出口正常收束。
- `人工暂停`
  F12 暂停后的正式状态。

补充说明：

- `正常结束`、`手动结束` 等旧口径在归一时会被收束到 `人工暂停` 等当前枚举，不应再当成新的正式状态扩散。

## 自动恢复为 `已准备` 的规则

当前自动恢复规则是固定的：

- 当前状态为 `余额不足`、`账号限制` 或 `抢购时长已到`
- 冷却剩余时间 `<= 0`

满足时，系统会把状态自动恢复为 `已准备`。

网页手动改成 `已准备` 时，也要同步满足：

- 可运行时间恢复为 2 小时 40 分
- 冷却剩余时间归零

下一份建议阅读： [04_operations_and_acceptance.md](04_operations_and_acceptance.md)
