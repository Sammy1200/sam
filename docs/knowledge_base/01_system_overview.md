# 系统总览

这份文档用于解释当前系统是怎么连起来工作的。重点是启动链路、主流程、数据流和系统边界。

## 先看版 / 单页总图

```text
正式启动入口
  古墓迷途.cmd
  -> scripts/run_via_task.ps1
  -> scripts/task_launcher.ps1
  -> main.py

main.py
  ├─ 正常模式
  │   -> 读 canonical SQLite
  │   -> 冷却判断 / 等待
  │   -> 预上架
  │   -> 抢购循环
  │   -> 定时上架
  │   -> 最终写回
  │   -> 切区 / 换号调度
  └─ 临时抢购模式 [2]
      -> 预上架
      -> 抢购循环
      -> 定时上架
      -> 定向切换链

展示 / 辅助层
  overlay
  本机网页
  远端镜像
  /public-snapshot（只查看 + 刷新按钮）

真源边界
  canonical SQLite = 唯一真实数据源
  runtime / overlay / web / snapshot = 展示或辅助，不是真源
```

## 主流程总览

默认主流程可以概括为：

`正式启动入口`  
-> `计划任务高权限启动 main.py`  
-> `main.py 检查管理员权限、网页服务、OCR、模板、截图引擎`  
-> `从启动器识别当前执行位`  
-> `按执行位 / 昵称读取 canonical SQLite`  
-> `自动解析当前应进的大区`  
-> `启动器进游戏并进入交易行`  
-> `执行预上架流程`  
-> `判断账号是否还在冷却期，必要时等待`  
-> `进入抢购主循环`  
-> `过程中按规则做余额检测、轻量落库、定时上架`  
-> `到达结束条件后最终写回 canonical`  
-> `按执行位规则切区或换号`  
-> `新账号再次先上架，再进入抢购`

临时抢购模式是旁路入口：

- 启动菜单 `[2]` 进入临时抢购模式
- 它复用主脚本中段链路：`预上架 -> 抢购循环 -> 定时上架`
- 不先读当前账号 canonical 主表
- 不建立正常模式那套 canonical SQLite 账号上下文
- 不接线程 5 的轻量落库、最终写回
- 不接线程 6 的正常换号 / 换区调度尾链
- 运行态基线库存从 `0` 开始
- 只在 `余额不足`、`抢购时长已到`、`账号限制` 这 3 类结束条件下，进入定向切换链
- 定向切换成功后，再接回正常“预上架 -> 抢购”链路

它不是正常模式的替代品，而是独立的临时模式入口。

## 数据流总览

当前系统不是“只有一个数据库”的简单脚本，而是由真源、运行态、展示层和镜像层组成。

### 1. canonical SQLite

canonical SQLite 是唯一真实数据源，负责保存：

- 账号基础字段
- 当前轮次字段
- 状态字段
- 时间字段
- 机器级汇总表

绝大多数正式判定都应以它为准。

### 2. runtime state

`state.py` 中的全局变量是当前进程运行态，用于承接：

- 当前账号
- 当前执行位
- 抢购/上架计数
- 当前余额
- 暂停状态
- 切换链路状态
- 当前轮次是否已最终写回

运行态是“正在执行时的内存视图”，不是最终真源。

### 3. runtime 辅助快照

`thread6_runtime.sqlite3` 记录当前执行位运行快照，用来辅助网页和诊断：

- 当前执行位
- 当前昵称
- 当前账号索引
- 当前大区索引
- 各执行位昵称映射
- runtime 快照更新时间

它是辅助快照，不是 canonical。

### 4. overlay

悬浮窗直接读运行态，不直接做业务决策。它的职责是：

- 展示当前状态
- 展示计分板
- 展示日志
- 触发暂停 / 恢复

### 5. web view

网页层通过 `account_view_repo.py` 读取 canonical 和 runtime 辅助快照，拼出可阅读页面：

- 首页列表
- 详情页
- 运行态健康信息
- 本机机器级汇总

网页最小修改也必须回写 canonical，并做回读确认后才算生效。

### 6. remote snapshot / remote mirror

双机场景下，远端数据先被整理成最小快照，再落到本机镜像库：

- 远端镜像库是 `remote_sync_mirror.sqlite3`
- 远端镜像用于展示、汇总和刷新
- 远端镜像不是 canonical

## 当前系统边界图

```text
正式启动入口
  ├─ scripts/register_scheduled_task.ps1   首次初始化
  ├─ 古墓迷途.cmd                          日常启动
  └─ scripts/run_via_task.ps1              触发计划任务
           |
           v
      scripts/task_launcher.ps1
           |
           v
         main.py
           |
           +--> OCR / 模板 / 截图引擎
           +--> overlay.py
           +--> purchase.py
           +--> listing.py
           +--> switch.py
           +--> web_view_server.py
           |
           +--> state.py                    进程内运行态
           +--> thread6_runtime.sqlite3     runtime 辅助快照
           +--> canonical SQLite            唯一真实数据源
           |
           +--> account_view_repo.py        网页读取与最小修改
           +--> remote_sync.py              最小快照 / 镜像
                    |
                    v
              remote_sync_mirror.sqlite3    远端镜像，不是真源
```

## 读这份文档时要记住的边界

- `main.py` 是唯一代码入口，但不是人工日常启动入口。
- canonical SQLite 和 runtime 快照不是一个层级。
- 网页页面能修改，不等于网页是主真源。
- 远端镜像能展示，不等于远端镜像能替代本机 canonical。

下一份建议阅读： [02_module_map.md](02_module_map.md)
