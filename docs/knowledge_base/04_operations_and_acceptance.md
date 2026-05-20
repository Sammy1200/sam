# 运行、验收与排错入口

这份文档用于统一“怎么启动、怎么验收、怎么判断读的是哪套 live 数据、出问题先看哪里”。

## 首次初始化

首次机器初始化只允许使用：

- `.\scripts\register_scheduled_task.ps1`

它做的事情是：

- 申请管理员权限
- 注册固定名称的计划任务 `codex-PYjiaoben-Launcher`
- 让后续启动统一走高权限链路

如果没有先注册这个计划任务，日常启动入口不会完整工作。

## 日常启动

日常启动只允许使用：

- `.\古墓迷途.cmd`
- `.\scripts\run_via_task.ps1`

这条链路会：

- 把“本次应启动的项目目录”写入 `%LOCALAPPDATA%\codex-PYjiaoben\task_target_path.txt`
- 触发计划任务
- 由 `scripts/task_launcher.ps1` 在目标目录下调用该 worktree 的 `.venv\Scripts\python.exe main.py`
- 设置环境标记 `FROM_SCHEDULED_TASK=1`

结论是：

- `main.py` 仍是代码入口
- 但运维入口已经切到“计划任务 + 启动器脚本”

## worktree 内验收

如果你在 worktree 或当前仓库里做了改动，验收入口仍应走：

- `.\scripts\run_via_task.ps1`

原因不是形式问题，而是这条脚本会把“当前 worktree 根目录”写到本地配置文件中，再由计划任务读取并启动对应目录。这样才能保持：

- 高权限
- 与正式链路一致
- 不直接绕开计划任务启动器

## 启动器当前入口

当前启动器界面默认有六种入口：

- `登录界面启动`
- `启动页上架模式`
- `临时抢购模式`
- `暴力模式`
- `饰品抢购模式`
- `装备抢购模式`

启动器还有 `功能设置` 按钮，点击后打开 `参数设置` 弹窗：

- `全局设置` 里的 `启用上架` 是本次启动级别上架总开关，保存到 `C:\py666\local_switch_account_config.json`
- 关闭 `启用上架` 后，`启动页上架模式` 按钮不可点击
- 关闭 `启用上架` 后选择其他入口，本次启动内所有账户、所有场景都跳过上架，包括预上架、换号后上架、临时模式上架和 10 分钟循环上架
- `石头设置` 支持 `前缀抢购` 和 `固定上下限抢购` 二选一；固定上下限按含等于的石头价格范围判断
- `装备设置` 支持设置装备抢购价格上下限；默认仍等价于 `50000 < 价格 < 4200000`
- 旧的 `C:\py666\launcher_preferences.json` 只在 `local_switch_account_config.json` 缺少 `listing_enabled` 时兼容读取；保存参数设置后真实来源切到 `local_switch_account_config.json`

其中：

- `登录界面启动` 继续沿原链路：识别当前执行位 -> 读 canonical -> 自动解析大区 -> 进游戏 -> 按 `启用上架` 决定是否预上架 -> 抢购
- `启动页上架模式` 是独立链路：只筛当前本机执行位范围中余额低于 `5 亿` 且状态不是 `账号限制` 的账号，完成上架后直接继续找下一个账号；当全部扫描完成后，自动切回正常模式继续后续抢购链路
- `临时抢购模式` 继续沿原临时模式链路，不受启动页上架模式影响，但会按 `启用上架` 决定是否执行临时模式预上架
- `暴力模式` 从交易行页面启动，不登录、不上架、不换号、不入库；交易行正常时先沿用正常模式识别余额，再刷新进入道具详情页，详情页未命中 `meihuo.png` 时直接执行 `购买 -> 确定`，不点击第一件商品；店铺异常走正常店铺恢复动作；余额不足、账号限制、未知异常、抢购上限等代码触发结束时会微信推送本机编号与本轮成功/失败汇总
- `饰品抢购模式` 从启动页进入正常账号库链路，全程不上架；换号/切区沿用正常链路，切换后进入饰品交易行继续饰品坐标轮询
- `饰品抢购模式` 运行数据只写饰品库 `C:\py666\accessory_account_stats.sqlite3`；正常石头库仍是 `C:\py666\account_stats.sqlite3`
- `装备抢购模式` 从启动页进入正常账号库链路，全程不上架；完成筛选保存后进入装备详情页循环抢购，价格识别不使用正常模式颜色守卫，不新增装备独立 SQLite

## 如何判断当前命中的是哪套 live 数据 / 配置

当前 live 路径解析由 `live_paths.py` 统一处理，优先级是：

1. `C:\py666`
2. 项目根目录回退位置

重点文件包括：

- 石头库 SQLite 真源：`account_stats.sqlite3`
- 饰品库 SQLite 真源：`accessory_account_stats.sqlite3`
- 本机换号配置：`local_switch_account_config.json`
- 本机网页同步配置：`local_web_sync_config.json`
- 旧启动器偏好：`launcher_preferences.json`（仅兼容读取旧上架开关）
- 昵称模板目录：`nichen`

判断当前命中来源时，优先看：

- 控制台 / 日志中的 `[live-path] ... 来源=live_root / project_fallback`
- 网页层 `source_diagnostics` 或源摘要
- `account_db.py` 初始化日志

## 验收与排错的第一入口

### 启动失败

先看：

- `scripts/register_scheduled_task.ps1`
- `scripts/run_via_task.ps1`
- `scripts/task_launcher.ps1`
- 计划任务是否仍存在
- `.venv\Scripts\python.exe` 和 `main.py` 是否都在目标 worktree 下

### 账号读库或状态异常

先看：

- `account_db.py`
- `round_persistence.py`
- `account_view_repo.py`
- live 路径日志是否命中了错误数据库

账号状态中 `禁止` 只能在本机网页手动选择。命中 `禁止` 的执行位不会进入抢购、饰品、装备、临时模式切回正常模式或启动页上架候选；登录界面启动时若当前执行位为 `禁止`，脚本会先切到下一个非 `禁止` 执行位。若所有可切换执行位均为 `禁止`，脚本应暂停并提示无可用执行位。

### 抢购问题

先看：

- `purchase.py`
- `config.py`
- 必要时补看 `vision.py` 和 `state.py`

如果日志出现 `Desktop duplication access loss`、`HRESULT=0x887A0026` 或 `DXCamera` 截图线程异常，通常是远程连接、显示器切换、锁屏/解锁等导致 DXGI 截图会话失效。当前截图层会自动重建截图引擎并继续等待新画面；若仍无法恢复，优先确认远程会话是否已回到可见桌面、游戏窗口是否仍存在。

### 上架问题

先看：

- `listing.py`
- `config.py`
- 必要时补看 `vision.py`

### 换号 / 切区问题

先看：

- `switch.py`
- `local_switch_account_config.py`
- `config.py`

### 网页 / 同步问题

- 查看页和公网页可在 `石头库 / 饰品库` 间切换；切换后表头语义同步变为 `道具库存/余额` 或 `饰品库存/金币`
- 本机查看页保存时必须携带当前 `db_mode`，切到哪个库就写哪个库，并做回读确认
- 公网页保持只查看和刷新；远端镜像按 `db_mode` 分开保存，石头库和饰品库快照互不覆盖

先看：

- `web_view_server.py`
- `account_view_repo.py`
- `machine_sync_config.py`
- `remote_sync.py`

## 常见误区

- 把当前 worktree 当成 live 数据根目录。
- 把网页页面当成真源。
- 把示例配置文件当成真实本机配置。
- 把 `python main.py` 当成日常启动方式。
- 把 runtime 辅助快照当成 canonical。

## 当前验收口径

当前项目的验收口径仍以 `AGENTS.md` 为准，但可以先记住：

- 只改文档、注释、纯日志文案，可以不运行。
- 小范围单模块修复，先做轻验证。
- 改运行流程、主入口、换号流程、上架流程、悬浮窗恢复逻辑、抢购主循环、跨模块联动时，需要真实运行验证。
- 新增或修改启动器入口、启动页上架模式、独立上架调度链时，也属于需要真实运行验证的范围。

不要把静态检查说成运行验证。

下一份建议阅读： [05_feature_switch_and_dispatch.md](05_feature_switch_and_dispatch.md)
