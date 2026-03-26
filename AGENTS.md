# 项目说明：游戏自动抢购 + 自动上架脚本

## 项目结构

project/
├── main.py          # 唯一入口：提权→选模式→加载资源→启动
├── config.py        # 所有常量/坐标/阈值/路径，禁止写逻辑代码
├── state.py         # 所有全局可变状态变量，禁止写函数逻辑
├── utils.py         # 底层键鼠操作、sleep、剪贴板、GC工具
├── vision.py        # 截图裁剪、模板匹配、OCR、余额识别、容量识别
├── overlay.py       # OSD悬浮窗、ui_print、计分板、暂停控制
├── listing.py       # 自动上架子系统
├── purchase.py      # 抢购主循环 + 余额/限制检测 + 推送
├── logo/            # 图片模板资源（只读，绝对不修改）
│   ├── jiage/       # 价格数字模板 0-9.png
│   ├── tezhengtu/   # 特征图模板（chenggong/dianpu/jiaoyihang/goumai/meihuo/diyici）
│   └── shangjia/    # 上架相关模板（pojiaoshi/tishi/shangjiatan/容量数字0-9/slash）
└── AGENTS.md        # 本文件


## 技术栈

- Python 3.10+
- dxcam（屏幕捕获，BGRA格式，target_fps=144）
- OpenCV（模板匹配，TM_CCOEFF_NORMED）
- rapidocr-onnxruntime（本地OCR引擎）
- pyautogui（仅用于 FAILSAFE=False 设置）
- ctypes（Win32 API 键鼠底层调用、管理员提权、进程优先级）
- tkinter（OSD悬浮窗，daemon线程运行）
- keyboard（F12全局热键，暂停/恢复）
- requests（pushplus推送通知）
- dxcam 帧获取后必须 .copy()，通过 safe_get_frame() 封装


## 模块依赖方向（单向，无循环）

main.py
  ├── config.py      （纯常量，不导入任何项目模块）
  ├── state.py       （纯变量，只导入 pyautogui）
  ├── utils.py       ← config, state
  ├── vision.py      ← config, state, utils
  ├── overlay.py     ← state, utils
  ├── listing.py     ← config, state, utils, vision, overlay
  └── purchase.py    ← config, state, utils, vision, overlay, listing


## 编码规范

1. 全局可变状态**只在 state.py 中定义**，其他模块通过 `import state` 后用 `state.xxx` 读写，**禁止在其他文件中用 global 关键字定义新的全局变量**
2. 所有 dxcam 帧获取必须用 `safe_get_frame(camera)` 并返回 `.copy()`
3. 修改任何文件后，**不得破坏现有功能**，必须保持向后兼容
4. 代码注释用**中文**
5. 坐标、阈值、路径等魔法数字**只允许出现在 config.py**
6. **禁止删除任何现有功能**，只允许新增或优化
7. 每次修改后必须说明：**改了什么、为什么改、怎么验证**
8. 函数命名用 snake_case，变量命名与现有代码风格一致
9. 所有 sleep/wait 必须支持 `state.IS_PAUSED` 中断检查
10. 新增功能如果涉及多个模块，说明每个模块改了什么


## 关键约束（红线，绝对不可违反）

- **禁止修改 logo/ 目录下的任何图片文件**
- **禁止更改抢购主循环的时序参数**（CONFIRM_DELAY, PRE_EXIT_CLICK_DELAY, EXIT_DELAY, MISMATCH_EXIT_DELAY 的值）
- **禁止移除管理员提权逻辑**（main.py 中的 is_admin 检查）
- **禁止引入新的第三方依赖**（除非用户明确要求）
- **禁止修改 pushplus 推送 token**
- **禁止改变模块依赖方向**（不能产生循环导入）
- **禁止在 config.py 中写函数或 import 除 os 以外的模块**
- **禁止在 state.py 中写函数**


## state.py 中管理的关键状态变量

| 变量名 | 类型 | 用途 |
|--------|------|------|
| IS_PAUSED | bool | F12暂停控制 |
| start_mode | int | 0未选/1定时/2先上架 |
| target_stop_seconds | int | 定时暂停秒数 |
| success_count | int | 抢购成功次数 |
| fail_count | int | 抢购失败次数 |
| total_listed_count | int | 累计上架件数 |
| limit_count | int | 连续空置计数 |
| unknown_page_count | int | 未知页面计数 |
| total_running_time | float | 累计运行时间 |
| last_resume_time | float/None | 上次恢复时间戳 |
| last_list_time | float | 上次上架时间 |
| current_balance | str | 当前余额显示 |
| ocr_engine | object | RapidOCR实例 |
| temp_jiaoyi | ndarray | 交易行模板 |
| TEMP_ITEM | ndarray | 上架道具模板 |
| TEMP_TISHI | ndarray | 提示弹窗模板 |
| TEMP_POPUP | ndarray | 上架弹窗模板 |
| DIGIT_TEMPLATES | dict | 容量数字模板 |
| overlay_root | Tk | 悬浮窗根对象 |
| log_text_var | StringVar | 日志显示变量 |
| score_var | StringVar | 计分板显示变量 |
| log_lines | list | 日志行缓存 |


## 核心业务流程

1. **启动流程**：管理员提权 → 选模式(定时/上架) → 加载OCR引擎 → 加载所有模板 → 启动dxcam → 启动悬浮窗
2. **上架流程**：进入背包 → 读取容量 → 循环(扫描道具→点击→等弹窗→输入价格→验证→确认) → 退出背包
3. **抢购流程**：截帧 → 模板匹配识别价格 → 价格区间判断 → 点击购买确认 → 检测结果(成功/失败/售空/异常) → 等待+余额检测 → 刷新 → 循环
4. **异常处理**：空置计数→限制暂停、未知页面→自愈/死锁推送、余额不足→暂停、卡死→推送


## 测试验证方式

- 脚本必须能直接 `python main.py` 运行
- 修改后需确认以下全流程无报错：
  1. 启动 → 选择模式
  2. 上架流程完整执行
  3. 抢购主循环正常运行
  4. F12暂停 → F12恢复
  5. 悬浮窗正常显示计分板和日志
- 如果只修改单个模块，至少确认该模块的 import 无报错、相关函数签名未变


## 给 Codex 的工作要求

1. 接到任务后，先阅读相关模块的完整代码，理解上下文再动手
2. 修改代码前，先说明修改方案，列出要改的文件和函数
3. 修改后，给出验证步骤
4. 如果任务描述不清晰，先提问确认，不要猜测需求
5. 优先使用最小改动原则，能改一行不改十行
