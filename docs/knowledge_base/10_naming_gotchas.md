# 10 命名陷阱与历史遗留

> 本项目存在一些"名字和实际行为不一致"的地方。新接手必读，否则必踩坑。

---

## 陷阱清单

### 1. `persist_minimal_item_balance_sync` vs `baseline_item_count`

| 维度 | 说明 |
|---|---|
| 函数名 | `persist_minimal_item_balance_sync`（含 `minimal_item_balance`） |
| 实际操作字段 | `state.baseline_item_count` |
| 原因 | 历史重构时字段改名了，函数名没跟着改 |
| 决策 | 暂不改名，改名会牵连 round_persistence / listing / purchase 多个模块 |
| 踩坑表现 | 新人看到函数名，去找 `state.minimal_item_balance`，发现不存在 |

### 2. `minimal_item_balance` 这个名字

| 维度 | 说明 |
|---|---|
| 当前状态 | **不是任何模块的正式属性名** |
| 容易误以为 | 是库存变量（因为持久化函数名含此词） |
| 正确变量 | `state.baseline_item_count` |
| 踩坑表现 | `getattr(state, "minimal_item_balance", "?")` 永远返回 `"?"` |

---

## 如何避免踩坑

1. **查字段先看 08 文档的 canonical 字段表**，不要从函数名反推字段名
2. **查函数签名先看 08 文档的接口签名表**，不要猜参数
3. 遇到命名不一致的新案例，**立即补充到本文档**

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2025-01 | 初建：记录 persist_minimal_item_balance_sync 命名陷阱 |
