# 09 UI 规范与悬浮窗约定

> 所有 overlay / GUI 相关开发必须遵守本文档约定。

---

## 一、配色体系（深褐色主题）

| 用途 | 色值 | 说明 |
|---|---|---|
| 主背景 | `#1c1714` | 所有面板底色 |
| 标题栏背景 | `#251e19` | header 区域 |
| 输入框背景 | `#2a211a` | Entry 控件 |
| 主文字 | `#e0d8d0` | 标题、正文 |
| 次要文字 | `#9a918a` | 标签、说明 |
| 强调色 | `#6b5d50` | 按钮默认态 |
| 强调色 hover | `#8a7a6a` | 按钮悬停 |
| 成功提示 | `#7acc7a` | 绿色 |
| 错误提示 | `#e07070` | 红色 |
| 边框 | `#3a3028` | 输入框、面板边框 |
| 输入框文字 | `#f0ece8` | Entry 内文字 |

**不使用透明度**，所有面板实底。
**不使用蓝紫色系**（如 `#1a1a2e`、`#0f3460` 等早期配色已废弃）。

---

## 二、字体约定

| 场景 | 字体 | 大小 | 粗细 |
|---|---|---|---|
| 标题 | Microsoft YaHei UI | 11 | bold |
| 标签/正文 | Microsoft YaHei UI | 9 | normal |
| 输入框/数字 | Consolas | 10 | normal |
| 按钮文字 | Microsoft YaHei UI | 9 | bold |
| 提示消息 | Microsoft YaHei UI | 8 | normal |

---

## 三、悬浮窗架构规则

1. **所有 UI 操作必须通过 `enqueue_overlay_task()` 投递**，不允许跨线程直接操作 tkinter
2. overlay 主窗口（显示倒计时、上架/抢购状态）是常驻窗口
3. 子面板（如 param_editor）是 `Toplevel`，跟随 overlay 生命周期
4. F12 暂停时 `show_param_editor()`，恢复时 `destroy_param_editor()`
5. 子面板默认收起，减少遮挡

---

## 四、新增 UI 组件检查清单

新增任何 overlay 子面板时，确认以下几点：
- [ ] 配色是否使用本文档色值
- [ ] 是否通过 `enqueue_overlay_task` 投递
- [ ] 是否有 `show_xxx()` 和 `destroy_xxx()` 成对接口
- [ ] 公开接口签名是否已登记到 08 文档
