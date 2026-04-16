# 08 Canonical 字段清单 & 跨模块接口签名

> 本文档解决一个问题：拿到一个字段名或函数名，立刻知道它的类型、谁读谁写、函数签名是什么。
> 补充 03_runtime_and_data.md 中未展开的细节。

---

## 一、Canonical 真源字段表

| 字段全名 | 所在模块 | 类型 | 初始值 | 谁写（场景） | 谁读（场景） |
|---|---|---|---|---|---|
| `state.baseline_item_count` | state.py | int | 0 | listing.py（上架成功 → -1）、purchase.py（抢购成功 → +1）、param_editor_gui.py（手动修改） | overlay 显示、param_editor_gui 面板、主流程判断库存 |
| `listing.LISTING_TARGET_PRICE` | listing.py | str | 从配置读取 | param_editor_gui.py（手动修改）、启动时从本地配置加载 | listing 主流程上架时引用 |
| `state.current_nickname` | state.py | str | "" | 登录/切号流程写入 | overlay 显示、日志 |
| `state.current_execution_slot` | state.py | int | 1 | 调度模块切换执行位 | overlay 显示、流程分支判断 |

---

## 二、跨模块持久化函数签名

### `persist_minimal_item_balance_sync()`
- **所在模块**：round_persistence.py
- **参数**：无（0 个参数）
- **行为**：读取 `state.baseline_item_count` 的当前内存值，写入持久化存储
- **返回值**：bool（True 成功 / False 失败）
- **调用顺序**：必须先改内存 `state.baseline_item_count = new_val`，再调用此函数
- ⚠️ **命名陷阱**：函数名含 `minimal_item_balance`，但实际操作的是 `state.baseline_item_count`，历史遗留不一致

### `save_listing_target_price(raw)`
- **所在模块**：local_switch_account_config.py
- **参数**：`raw`（str，新价格字符串）
- **行为**：将价格写入本地配置文件
- **返回值**：无显式返回，异常时抛出 Exception
- **调用后还需**：手动同步 `listing.LISTING_TARGET_PRICE = raw`

---

## 三、常见误用

| 错误写法 | 正确写法 | 原因 |
|---|---|---|
| `state.minimal_item_balance` | `state.baseline_item_count` | 前者不存在，getattr 会返回默认值 |
| `persist_minimal_item_balance_sync(new_val)` | 先 `state.baseline_item_count = new_val` 再 `persist_minimal_item_balance_sync()` | 函数不接受参数 |
