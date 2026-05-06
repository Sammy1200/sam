"""F9 暂停态计数悬浮窗。"""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from typing import Any


_counter_window = None


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
        self.jipo_scan_state = "primary"
        self.trade_scan_state = "jiaoyi"
        self.stop_scan_event = threading.Event()
        self.jipo_scan_thread = None
        self.trade_scan_thread = None
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

    def _configure_window(self) -> None:
        self.root.title("悬浮计数器")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0B111B")
        self.root.geometry("+200+200")
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

        for name in ("1jipo.png", "2jipo.png", "xiaohao.png", "jiaoyi.png", "wancheng.png"):
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
    except Exception:
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
