"""F9 暂停态计数悬浮窗。"""

import ctypes
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from typing import Any


_counter_window = None
_VK_NUMPAD_ADD = 0x6B
_VK_NUMPAD_SUBTRACT = 0x6D
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004


class FloatingCounter:
    def __init__(self, parent: tk.Misc, on_close=None) -> None:
        self.parent = parent
        self.on_close = on_close
        self.root = tk.Toplevel(parent)
        self.count = 0
        self.success_count = 0
        self.failure_count = 0
        self.is_editing_count = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.assets_dir = Path(__file__).resolve().parent
        self.primary_scan_region = (888, 480, 145, 148)
        self.primary_scan_interval_seconds = 0.1
        self.wait_scan_region = (618, 613, 82, 44)
        self.wait_scan_interval_seconds = 0.2
        self.jiaoyi_scan_region = (363, 227, 159, 49)
        self.jiaoyi_scan_interval_seconds = 1.0
        self.wancheng_scan_region = (911, 31, 101, 27)
        self.wancheng_scan_interval_seconds = 0.1
        self.match_threshold = 0.88
        self.quick_trade_points = (
            (1644, 1040), (1520, 1040), (1398, 1008),
            (1644, 920), (1520, 920), (1400, 920),
            (1644, 800), (1520, 800), (1400, 800),
            (1644, 676), (1520, 676), (1400, 676),
            (1644, 545), (1520, 545), (1400, 545),
            (1644, 420), (1520, 420), (1400, 420),
            (1644, 300), (1520, 300), (1400, 300),
            (1644, 166), (1520, 166), (1400, 166),
        )
        self.quick_trade_target_pos = (888, 500)
        self.quick_trade_full_region = (870, 537, 50, 51)
        self.quick_trade_complete_pos = (950, 888)
        self.quick_trade_drag_seconds = 0.005
        self.quick_trade_source_settle_seconds = 0.05
        self.quick_trade_hold_before_drag_seconds = 0.005
        self.quick_trade_complete_click_interval_seconds = 0.15
        self.quick_trade_check_after_drags = 0
        self.jipo_scan_state = "primary"
        self.trade_scan_state = "jiaoyi"
        self.stop_scan_event = threading.Event()
        self.quick_trade_cancel_event = threading.Event()
        self.jipo_scan_thread = None
        self.trade_scan_thread = None
        self.quick_trade_thread = None
        self.quick_trade_test_thread = None
        self.quick_trade_test_index = 0
        self.quick_trade_hotkey_after_id = None
        self.quick_trade_last_add_down = False
        self.quick_trade_last_subtract_down = False
        self.quick_trade_user32 = None
        self.quick_trade_mouse_user32 = None
        self.is_closed = False
        self._cv2: Any = None
        self._np: Any = None
        self._pyautogui: Any = None
        self.templates = self._load_templates()
        self.jiaoyi_scan_region = self._expand_region_to_template(
            self.jiaoyi_scan_region,
            "jiaoyi.png",
        )
        self.wancheng_scan_region = self._expand_region_to_template(
            self.wancheng_scan_region,
            "wancheng.png",
        )

        self._configure_window()
        self._build_ui()
        self._refresh_counter()
        self._refresh_result_counters()
        self._start_auto_scans()
        self._start_quick_trade_hotkey_listener()

    def _configure_window(self) -> None:
        self.root.title("悬浮计数器")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0B111B")
        self.root.geometry("+85+232")
        self.root.bind("<Escape>", self._request_shutdown)
        self.root.protocol("WM_DELETE_WINDOW", self._request_shutdown)

    def _build_ui(self) -> None:
        self.root.option_add("*Button.BorderWidth", 0)
        self.root.option_add("*Button.HighlightThickness", 0)

        self.main_frame = tk.Frame(
            self.root,
            bg="#0F1723",
            bd=0,
            padx=18,
            pady=18,
        )
        self.main_frame.pack()

        number_font = tkfont.Font(family="Microsoft YaHei UI", size=38, weight="bold")
        button_font = tkfont.Font(family="Microsoft YaHei UI", size=11, weight="bold")
        result_font = tkfont.Font(family="Microsoft YaHei UI", size=12, weight="bold")

        self.result_frame = tk.Frame(self.main_frame, bg="#0F1723")
        self.result_frame.pack(fill="x", pady=(0, 12))

        self.success_label = tk.Label(
            self.result_frame,
            text="成功 0",
            font=result_font,
            fg="#5EEAD4",
            bg="#132A30",
            padx=14,
            pady=8,
            cursor="hand2",
        )
        self.success_label.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.success_label.bind("<Button-1>", lambda event: self._change_count(3))

        self.failure_label = tk.Label(
            self.result_frame,
            text="失败 0",
            font=result_font,
            fg="#FCA5A5",
            bg="#2A1720",
            padx=14,
            pady=8,
            cursor="hand2",
        )
        self.failure_label.pack(side="left", expand=True, fill="x", padx=(6, 0))
        self.failure_label.bind("<Button-1>", lambda event: self._change_count(2))

        self.counter_frame = tk.Frame(self.main_frame, bg="#0F1723")
        self.counter_frame.pack(fill="x", pady=(4, 10))

        self.counter_label = tk.Label(
            self.counter_frame,
            text="0",
            font=number_font,
            fg="#F9FAFB",
            bg="#0F1723",
            anchor="center",
            justify="center",
            pady=6,
        )
        self.counter_label.pack(fill="x")
        self.counter_label.bind("<Button-1>", self._show_count_editor)

        self.control_frame = tk.Frame(self.main_frame, bg="#0F1723")
        self.control_frame.pack(fill="x")

        self.reset_button = tk.Button(
            self.control_frame,
            text="重置",
            font=button_font,
            bg="#17202D",
            fg="#E2E8F0",
            activebackground="#223047",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=16,
            pady=10,
            command=self._reset_count,
            cursor="hand2",
        )
        self.reset_button.pack(side="left", expand=True, fill="x")

        for widget in (
            self.root,
            self.main_frame,
            self.result_frame,
            self.counter_frame,
            self.control_frame,
        ):
            self._bind_drag(widget)

    def _bind_drag(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._drag_window)

    def _start_drag(self, event: tk.Event) -> None:
        self.drag_offset_x = event.x_root - self.root.winfo_x()
        self.drag_offset_y = event.y_root - self.root.winfo_y()

    def _drag_window(self, event: tk.Event) -> None:
        if self.is_closed:
            return
        x = event.x_root - self.drag_offset_x
        y = event.y_root - self.drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def _refresh_counter(self) -> None:
        if not self.is_closed:
            self.counter_label.config(text=str(self.count))

    def _show_count_editor(self, event: tk.Event | None = None) -> None:
        if self.is_closed or self.is_editing_count:
            return

        self.is_editing_count = True
        self.counter_label.pack_forget()

        self.count_entry = tk.Entry(
            self.counter_frame,
            font=("Microsoft YaHei UI", 34, "bold"),
            fg="#F9FAFB",
            bg="#0F1723",
            insertbackground="#F9FAFB",
            justify="center",
            relief="flat",
            width=4,
        )
        self.count_entry.insert(0, str(self.count))
        self.count_entry.pack(pady=6)
        self.count_entry.focus_set()
        self.count_entry.select_range(0, tk.END)
        self.count_entry.bind("<Return>", self._commit_count_editor)
        self.count_entry.bind("<Escape>", self._cancel_count_editor)
        self.count_entry.bind("<FocusOut>", self._cancel_count_editor)

    def _commit_count_editor(self, event: tk.Event | None = None) -> str:
        raw_value = self.count_entry.get().strip()

        try:
            if raw_value.startswith(("+", "-")):
                self.count += int(raw_value)
            else:
                self.count = int(raw_value)
        except ValueError:
            self._cancel_count_editor()
            return "break"

        self._close_count_editor()
        self._refresh_counter()
        return "break"

    def _cancel_count_editor(self, event: tk.Event | None = None) -> str:
        self._close_count_editor()
        return "break"

    def _close_count_editor(self) -> None:
        if not self.is_editing_count:
            return

        try:
            self.count_entry.destroy()
        except Exception:
            pass
        if not self.is_closed:
            self.counter_label.pack(fill="x")
        self.is_editing_count = False

    def _refresh_result_counters(self) -> None:
        if self.is_closed:
            return
        self.success_label.config(text=f"成功 {self.success_count}")
        self.failure_label.config(text=f"失败 {self.failure_count}")

    def _change_count(self, amount: int) -> None:
        if self.is_closed:
            return
        self.count += amount
        self._refresh_counter()

    def _safe_change_count(self, amount: int) -> None:
        self._schedule_ui(lambda: self._change_count(amount))

    def _record_success(self) -> None:
        if self.is_closed:
            return
        self.success_count += 1
        self._refresh_result_counters()

    def _record_failure(self) -> None:
        if self.is_closed:
            return
        self.failure_count += 1
        self._refresh_result_counters()

    def _safe_record_success(self) -> None:
        self._schedule_ui(self._record_success)

    def _safe_record_failure(self) -> None:
        self._schedule_ui(self._record_failure)

    def _reset_count(self) -> None:
        if self.is_closed:
            return
        self.count = 0
        self.success_count = 0
        self.failure_count = 0
        self._refresh_counter()
        self._refresh_result_counters()

    def _load_detection_modules(self) -> bool:
        if self._cv2 is not None and self._np is not None and self._pyautogui is not None:
            return True
        try:
            import cv2
            import numpy as np
            import pyautogui
        except Exception:
            return False
        self._cv2 = cv2
        self._np = np
        self._pyautogui = pyautogui
        return True

    def _load_templates(self) -> dict[str, Any]:
        templates: dict[str, Any] = {}
        if not self._load_detection_modules():
            return templates

        for name in ("1jipo.png", "2jipo.png", "xiaohao.png", "jiaoyi.png", "wancheng.png", "manle.png"):
            image = self._cv2.imread(str(self.assets_dir / name), self._cv2.IMREAD_COLOR)
            if image is not None:
                templates[name] = image
        return templates

    def _expand_region_to_template(self, region: tuple[int, int, int, int], template_name: str) -> tuple[int, int, int, int]:
        template = self.templates.get(template_name)
        if template is None:
            return region

        x, y, width, height = region
        template_height, template_width = template.shape[:2]
        return (x, y, max(width, template_width), max(height, template_height))

    def _start_auto_scans(self) -> None:
        if not self.templates:
            return
        self.stop_scan_event.clear()
        if not self.jipo_scan_thread or not self.jipo_scan_thread.is_alive():
            self.jipo_scan_thread = threading.Thread(target=self._jipo_scan_loop, daemon=True)
            self.jipo_scan_thread.start()
        if not self.trade_scan_thread or not self.trade_scan_thread.is_alive():
            self.trade_scan_thread = threading.Thread(target=self._trade_scan_loop, daemon=True)
            self.trade_scan_thread.start()

    def _stop_auto_scans(self) -> None:
        self.stop_scan_event.set()

    def _wait_scan_threads_stopped(self) -> None:
        for thread in (self.jipo_scan_thread, self.trade_scan_thread):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=0.3)

    def _start_quick_trade_hotkey_listener(self) -> None:
        if sys.platform != "win32":
            return

        try:
            user32 = ctypes.windll.user32
            user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
            user32.GetAsyncKeyState.restype = ctypes.c_short
        except Exception:
            return

        self.quick_trade_user32 = user32
        self.quick_trade_mouse_user32 = user32
        self._poll_quick_trade_hotkey()

    def _poll_quick_trade_hotkey(self) -> None:
        if self.is_closed or self.quick_trade_user32 is None:
            return

        try:
            is_add_down = bool(self.quick_trade_user32.GetAsyncKeyState(_VK_NUMPAD_ADD) & 0x8000)
            if is_add_down and not self.quick_trade_last_add_down:
                self._toggle_quick_trade()
            self.quick_trade_last_add_down = is_add_down
            is_subtract_down = bool(self.quick_trade_user32.GetAsyncKeyState(_VK_NUMPAD_SUBTRACT) & 0x8000)
            if is_subtract_down and not self.quick_trade_last_subtract_down:
                self._run_quick_trade_test_step()
            self.quick_trade_last_subtract_down = is_subtract_down
            self.quick_trade_hotkey_after_id = self.root.after(50, self._poll_quick_trade_hotkey)
        except Exception:
            self.quick_trade_hotkey_after_id = None

    def _cancel_quick_trade_hotkey_listener(self) -> None:
        after_id = self.quick_trade_hotkey_after_id
        self.quick_trade_hotkey_after_id = None
        if after_id is None:
            return
        try:
            self.root.after_cancel(after_id)
        except Exception:
            pass

    def _is_quick_trade_running(self) -> bool:
        return bool(self.quick_trade_thread and self.quick_trade_thread.is_alive())

    def _is_quick_trade_test_running(self) -> bool:
        return bool(self.quick_trade_test_thread and self.quick_trade_test_thread.is_alive())

    def _toggle_quick_trade(self) -> None:
        if self.is_closed:
            return
        if self._is_quick_trade_running():
            self.quick_trade_cancel_event.set()
            return
        if not self._load_detection_modules():
            return

        self.quick_trade_cancel_event.clear()
        self.quick_trade_thread = threading.Thread(target=self._quick_trade_loop, daemon=True)
        self.quick_trade_thread.start()

    def _run_quick_trade_test_step(self) -> None:
        if self.is_closed or self._is_quick_trade_running() or self._is_quick_trade_test_running():
            return
        if not self.quick_trade_points:
            return

        self.quick_trade_cancel_event.clear()
        self.quick_trade_test_thread = threading.Thread(target=self._quick_trade_test_step_loop, daemon=True)
        self.quick_trade_test_thread.start()

    def _quick_trade_test_step_loop(self) -> None:
        try:
            old_pause = getattr(self._pyautogui, "PAUSE", None) if self._load_detection_modules() else None
            if old_pause is not None:
                self._pyautogui.PAUSE = 0
            index = self.quick_trade_test_index % len(self.quick_trade_points)
            self._quick_trade_drag(self.quick_trade_points[index], index)
            self.quick_trade_test_index = (index + 1) % len(self.quick_trade_points)
        except Exception:
            return
        finally:
            if self._pyautogui is not None and old_pause is not None:
                try:
                    self._pyautogui.PAUSE = old_pause
                except Exception:
                    pass

    def _quick_trade_loop(self) -> None:
        old_pause = getattr(self._pyautogui, "PAUSE", None)
        try:
            self._pyautogui.PAUSE = 0
            for index, source_pos in enumerate(self.quick_trade_points):
                if self._should_stop_quick_trade():
                    return
                if index >= self.quick_trade_check_after_drags and self._detect_quick_trade_full():
                    self._finish_quick_trade_full()
                    return
                if self._should_stop_quick_trade():
                    return
                self._quick_trade_drag(source_pos, index)
        except Exception:
            return
        finally:
            if old_pause is not None:
                try:
                    self._pyautogui.PAUSE = old_pause
                except Exception:
                    pass

    def _should_stop_quick_trade(self) -> bool:
        return self.is_closed or self.stop_scan_event.is_set() or self.quick_trade_cancel_event.is_set()

    def _detect_quick_trade_full(self) -> bool:
        if self._should_stop_quick_trade():
            return False
        return self._detect_template_in_region(self.quick_trade_full_region, ("manle.png",)) == "manle.png"

    def _quick_trade_drag(self, source_pos: tuple[int, int], index: int) -> None:
        if self._should_stop_quick_trade():
            return

        target_x, target_y = self.quick_trade_target_pos
        source_x, source_y = source_pos
        source_settle_seconds = self.quick_trade_source_settle_seconds
        hold_before_drag_seconds = self.quick_trade_hold_before_drag_seconds
        if self.quick_trade_mouse_user32 is not None:
            self._quick_trade_drag_with_win32(
                source_x,
                source_y,
                target_x,
                target_y,
                source_settle_seconds,
                hold_before_drag_seconds,
            )
            return

        self._quick_trade_drag_with_pyautogui(
            source_x,
            source_y,
            target_x,
            target_y,
            source_settle_seconds,
            hold_before_drag_seconds,
        )

    def _quick_trade_drag_with_win32(
        self,
        source_x: int,
        source_y: int,
        target_x: int,
        target_y: int,
        source_settle_seconds: float,
        hold_before_drag_seconds: float,
    ) -> None:
        user32 = self.quick_trade_mouse_user32
        if user32 is None:
            return

        mid_x = (source_x + target_x) // 2
        mid_y = (source_y + target_y) // 2
        delay = max(0.005, self.quick_trade_drag_seconds / 3)
        mouse_is_down = False
        try:
            user32.SetCursorPos(source_x, source_y)
            self._wait_quick_trade_interval(source_settle_seconds)
            if self._should_stop_quick_trade():
                return
            user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            mouse_is_down = True
            self._wait_quick_trade_interval(hold_before_drag_seconds)
            if self._should_stop_quick_trade():
                return
            time.sleep(delay)
            user32.SetCursorPos(mid_x, mid_y)
            time.sleep(delay)
            user32.SetCursorPos(target_x, target_y)
            time.sleep(delay)
        finally:
            if mouse_is_down:
                try:
                    user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                except Exception:
                    pass

    def _quick_trade_drag_with_pyautogui(
        self,
        source_x: int,
        source_y: int,
        target_x: int,
        target_y: int,
        source_settle_seconds: float,
        hold_before_drag_seconds: float,
    ) -> None:
        if not self._load_detection_modules():
            return

        mouse_is_down = False
        try:
            self._pyautogui.moveTo(source_x, source_y, duration=0)
            self._wait_quick_trade_interval(source_settle_seconds)
            if self._should_stop_quick_trade():
                return
            self._pyautogui.mouseDown(button="left")
            mouse_is_down = True
            self._wait_quick_trade_interval(hold_before_drag_seconds)
            if self._should_stop_quick_trade():
                return
            self._pyautogui.moveTo(target_x, target_y, duration=self.quick_trade_drag_seconds)
        finally:
            if mouse_is_down:
                try:
                    self._pyautogui.mouseUp(button="left")
                except Exception:
                    pass

    def _finish_quick_trade_full(self) -> None:
        if not self._load_detection_modules():
            return

        click_x, click_y = self.quick_trade_complete_pos
        for click_index in range(2):
            if self._should_stop_quick_trade():
                return
            self._pyautogui.click(click_x, click_y)
            if click_index == 0:
                self._wait_quick_trade_interval(self.quick_trade_complete_click_interval_seconds)

    def _wait_quick_trade_interval(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._should_stop_quick_trade():
                return
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))

    def _stop_quick_trade(self) -> None:
        self.quick_trade_cancel_event.set()
        for thread in (self.quick_trade_thread, self.quick_trade_test_thread):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=0.5)

    def _jipo_scan_loop(self) -> None:
        while not self.stop_scan_event.is_set():
            try:
                if self.jipo_scan_state == "primary":
                    matched_name = self._detect_primary_template()
                else:
                    matched_name = self._detect_wait_template()
            except Exception:
                if self.stop_scan_event.wait(self._current_jipo_scan_interval()):
                    break
                continue

            if self.stop_scan_event.is_set():
                break

            if self.jipo_scan_state == "primary":
                if matched_name == "2jipo.png":
                    self._handle_primary_detected_match(3, "success")
                    continue
                if matched_name == "1jipo.png":
                    self._handle_primary_detected_match(2, "failure")
                    continue
            elif matched_name == "xiaohao.png":
                self._handle_wait_detected_match()
                continue

            if self.stop_scan_event.wait(self._current_jipo_scan_interval()):
                break

    def _trade_scan_loop(self) -> None:
        while not self.stop_scan_event.is_set():
            try:
                if self.trade_scan_state == "jiaoyi":
                    matched_name = self._detect_jiaoyi_template()
                else:
                    matched_name = self._detect_wancheng_template()
            except Exception:
                if self.stop_scan_event.wait(self._current_trade_scan_interval()):
                    break
                continue

            if self.stop_scan_event.is_set():
                break

            if self.trade_scan_state == "jiaoyi" and matched_name == "jiaoyi.png":
                self.trade_scan_state = "wancheng"
                continue
            if self.trade_scan_state == "wancheng" and matched_name == "wancheng.png":
                self._safe_change_count(10)
                self.trade_scan_state = "jiaoyi"
                continue

            if self.stop_scan_event.wait(self._current_trade_scan_interval()):
                break

    def _current_jipo_scan_interval(self) -> float:
        if self.jipo_scan_state == "primary":
            return self.primary_scan_interval_seconds
        return self.wait_scan_interval_seconds

    def _current_trade_scan_interval(self) -> float:
        if self.trade_scan_state == "jiaoyi":
            return self.jiaoyi_scan_interval_seconds
        return self.wancheng_scan_interval_seconds

    def _detect_primary_template(self) -> str | None:
        return self._detect_template_in_region(
            self.primary_scan_region,
            ("2jipo.png", "1jipo.png"),
        )

    def _detect_wait_template(self) -> str | None:
        return self._detect_template_in_region(
            self.wait_scan_region,
            ("xiaohao.png",),
        )

    def _detect_jiaoyi_template(self) -> str | None:
        return self._detect_template_in_region(
            self.jiaoyi_scan_region,
            ("jiaoyi.png",),
        )

    def _detect_wancheng_template(self) -> str | None:
        return self._detect_template_in_region(
            self.wancheng_scan_region,
            ("wancheng.png",),
        )

    def _detect_template_in_region(self, region: tuple[int, int, int, int], template_names: tuple[str, ...]) -> str | None:
        if not self.templates or not self._load_detection_modules() or self.stop_scan_event.is_set():
            return None

        screenshot = self._pyautogui.screenshot(region=region)
        screenshot_bgr = self._cv2.cvtColor(self._np.array(screenshot), self._cv2.COLOR_RGB2BGR)

        for name in template_names:
            template = self.templates.get(name)
            if template is None:
                continue
            template_height, template_width = template.shape[:2]
            screenshot_height, screenshot_width = screenshot_bgr.shape[:2]
            if template_width > screenshot_width or template_height > screenshot_height:
                continue
            result = self._cv2.matchTemplate(screenshot_bgr, template, self._cv2.TM_CCOEFF_NORMED)
            _, max_value, _, _ = self._cv2.minMaxLoc(result)
            if max_value >= self.match_threshold:
                return name

        return None

    def _handle_primary_detected_match(self, amount: int, result_type: str) -> None:
        self._safe_change_count(amount)
        if result_type == "success":
            self._safe_record_success()
        else:
            self._safe_record_failure()
        self.jipo_scan_state = "waiting"

    def _handle_wait_detected_match(self) -> None:
        self.jipo_scan_state = "primary"

    def _schedule_ui(self, callback) -> None:
        if self.is_closed or self.stop_scan_event.is_set():
            return
        try:
            self.root.after(0, callback)
        except Exception:
            pass

    def _request_shutdown(self, event: tk.Event | None = None) -> str:
        if self.on_close:
            self.on_close(self)
        else:
            self.shutdown()
        return "break"

    def is_alive(self) -> bool:
        if self.is_closed:
            return False
        try:
            return bool(self.root.winfo_exists())
        except Exception:
            return False

    def shutdown(self) -> None:
        if self.is_closed:
            return
        self.is_closed = True
        self._cancel_quick_trade_hotkey_listener()
        self._stop_quick_trade()
        self._stop_auto_scans()
        self._wait_scan_threads_stopped()
        try:
            self._close_count_editor()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def _forget_counter(counter: FloatingCounter) -> None:
    global _counter_window
    if _counter_window is counter:
        _counter_window = None
    counter.shutdown()


def is_counter_open() -> bool:
    return bool(_counter_window and _counter_window.is_alive())


def show_counter(parent: tk.Misc) -> bool:
    global _counter_window
    if is_counter_open():
        return True
    try:
        _counter_window = FloatingCounter(parent, on_close=_forget_counter)
    except Exception as exc:
        print(f"[计数窗] 启动失败：{exc}")
        _counter_window = None
        return False
    return True


def destroy_counter() -> bool:
    global _counter_window
    counter = _counter_window
    _counter_window = None
    if counter is None:
        return False
    counter.shutdown()
    return True


def toggle_counter(parent: tk.Misc) -> str:
    if is_counter_open():
        destroy_counter()
        return "closed"
    if show_counter(parent):
        return "opened"
    return "failed"


def main() -> None:
    root = tk.Tk()
    root.withdraw()

    def _close_demo(counter: FloatingCounter) -> None:
        counter.shutdown()
        root.destroy()

    FloatingCounter(root, on_close=_close_demo)
    root.mainloop()


if __name__ == "__main__":
    main()
