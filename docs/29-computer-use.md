# 29. computer_use 计算机使用工具开发计划

> Zeloo 的 `browser_tools.py` 仅支持浏览器自动化。本文档记录需要开发的 computer_use 工具，赋予 AI 像真实用户一样操作计算机的能力。

## 29.1 能力概览

computer_use 工具让 AI Agent 能够像真实用户一样操作计算机：

```
┌──────────────────────────────────────────────────────┐
│                  computer_use 工具集                    │
├──────────────────────────────────────────────────────┤
│  screenshot  ──►  获取屏幕截图，AI 分析画面           │
│  mouse_move  ──►  移动鼠标指针                        │
│  mouse_click ──►  左键单击/双击/右键                 │
│  key_press   ──►  键盘按键（文字输入/快捷键）          │
│  scroll      ──►  页面/窗口滚动                      │
│  window_list ──►  列出所有窗口                       │
│  window_move ──►  移动/调整窗口                      │
│  terminal    ──►  在终端执行命令                     │
└──────────────────────────────────────────────────────┘
```

## 29.2 架构

```
tools/computer_use/
├── __init__.py
├── screenshot.py       # 屏幕截图
├── mouse.py            # 鼠标控制
├── keyboard.py         # 键盘控制
├── window_manager.py   # 窗口管理
├── display.py         # 显示信息
├── state_tracker.py    # 状态追踪
├── tools.py           # @tool 装饰器注册（11 个工具）
└── backends/          # 跨平台后端实现
    ├── __init__.py    # ComputerBackend ABC + get_backend() 工厂
    ├── windows.py     # WindowsBackend（pywinauto + pyautogui）
    ├── macos.py       # MacOSBackend（pyobjc Quartz）
    └── linux.py       # LinuxBackend（pyautogui + xdotool）
```

## 29.3 工具实现

### 29.3.1 screenshot.py

```python
# tools/computer_use/screenshot.py

class ScreenshotTool(BaseTool):
    name = "computer_screenshot"
    description = "获取屏幕截图"
    dangerous = False

    @tool(toolset="computer_use")
    def execute(
        self,
        region: str = "full",  # "full" | "window" | "rect"
        window_id: int | None = None,
        rect: tuple[int, int, int, int] | None = None,
    ) -> str:
        """获取屏幕截图，返回 base64 编码的 PNG。"""
        ...

@dataclass
class ScreenshotResult:
    base64: str           # base64 PNG
    width: int
    height: int
    format: str = "png"
```

### 29.3.2 mouse.py

```python
# tools/computer_use/mouse.py

class MouseMoveTool(BaseTool):
    name = "computer_mouse_move"
    description = "移动鼠标指针到指定位置"

    @tool(toolset="computer_use")
    def execute(self, x: int, y: int, relative: bool = False) -> str:
        """移动鼠标到绝对坐标或相对当前位置的偏移。"""

class MouseClickTool(BaseTool):
    name = "computer_mouse_click"
    description = "鼠标点击"

    @tool(toolset="computer_use")
    def execute(
        self,
        x: int,
        y: int,
        button: str = "left",   # "left" | "right" | "middle"
        click_type: str = "click",  # "click" | "double_click" | "triple_click"
    ) -> str:
        """在指定坐标点击鼠标。"""

class MouseScrollTool(BaseTool):
    name = "computer_mouse_scroll"
    description = "滚动鼠标"

    @tool(toolset="computer_use")
    def execute(self, x: int, y: int, delta_x: int = 0, delta_y: int = -300) -> str:
        """在指定位置滚动。delta_y 负值向上，正值向下。"""
```

### 29.3.3 keyboard.py

```python
# tools/computer_use/keyboard.py

class KeyPressTool(BaseTool):
    name = "computer_key_press"
    description = "按键"

    @tool(toolset="computer_use")
    def execute(
        self,
        key: str,  # "a" | "enter" | "ctrl+c" | "alt+tab"
        hold: list[str] | None = None,  # 按住修饰键
    ) -> str:
        """按下指定键。"""

class TextInputTool(BaseTool):
    name = "computer_text_input"
    description = "文本输入"

    @tool(toolset="computer_use")
    def execute(self, text: str, delay_ms: int = 0) -> str:
        """输入文本。delay_ms 控制字符间延迟。"""
```

### 29.3.4 window_manager.py

```python
# tools/computer_use/window_manager.py

class WindowListTool(BaseTool):
    name = "computer_window_list"
    description = "列出所有窗口"

    @tool(toolset="computer_use")
    def execute(self) -> list[dict]:
        return [
            {
                "id": 12345,
                "title": "VSCode - project.py",
                "bounds": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                "focused": True,
            },
            ...
        ]

class WindowFocusTool(BaseTool):
    name = "computer_window_focus"
    description = "聚焦窗口"

    @tool(toolset="computer_use")
    def execute(self, window_id: int | str) -> str:
        """通过窗口 ID 或标题聚焦窗口。"""

class WindowMoveTool(BaseTool):
    name = "computer_window_move"
    description = "移动或调整窗口"

    @tool(toolset="computer_use")
    def execute(self, window_id: int, x: int, y: int, width: int | None = None, height: int | None = None) -> str:
        """移动窗口到指定位置，可选调整尺寸。"""
```

## 29.4 后端实现

> 以下文件已实现于 `tools/computer_use/backends/`。

### 29.4.1 Windows 后端

已实现：`tools/computer_use/backends/windows.py` — `WindowsBackend`

主要依赖：`pyautogui` + `pygetwindow` + `Pillow`（截图）+ `ctypes`（显示信息）

```python
from tools.computer_use.backends import get_backend

backend = get_backend()  # Windows → WindowsBackend
result = backend.screenshot()
backend.mouse_move(100, 200)
windows = backend.list_windows()
```

### 29.4.2 macOS 后端

已实现：`tools/computer_use/backends/macos.py` — `MacOSBackend`

主要依赖：`pyautogui` + `Quartz`（CGDisplayCreateImage 截图）+ `Cocoa`（NSScreen）

### 29.4.3 Linux 后端

已实现：`tools/computer_use/backends/linux.py` — `LinuxBackend`

主要依赖：`pyautogui` + `xdotool`（窗口管理 / 显示信息）

### 29.4.4 后端工厂

```python
# tools/computer_use/backends/__init__.py

class ComputerBackend(ABC):
    """Protocol — 所有后端必须实现"""
    def screenshot(self, region: str = "full") -> ScreenshotResult: ...
    def mouse_move(self, x: int, y: int, relative: bool = False) -> MouseResult: ...
    def mouse_click(self, x, y, button, clicks) -> MouseResult: ...
    def mouse_drag(self, start_x, start_y, end_x, end_y, button) -> MouseResult: ...
    def key_press(self, key: str) -> bool: ...
    def text_input(self, text: str) -> bool: ...
    def hotkey(self, *keys: str) -> bool: ...
    def scroll(self, clicks: int, direction: str) -> bool: ...
    def list_windows(self) -> list[WindowInfo]: ...
    def focus_window(self, handle: int) -> bool: ...
    def get_display_info(self) -> dict: ...
    def is_available(self) -> bool: ...

def get_backend() -> ComputerBackend:
    """自动检测当前平台，返回对应后端实例"""
    ...
```
## 29.5 状态追踪器

```python
# tools/computer_use/state_tracker.py

class ComputerStateTracker:
    """追踪计算机操作历史，用于决策和去重。"""

    def __init__(self, max_history: int = 100):
        self.history: list[dict] = []
        self.max_history = max_history

    def record(self, action: dict) -> None:
        self.history.append(action)
        if len(self.history) > self.max_history:
            self.history.pop(0)

    def get_recent(self, n: int = 10) -> list[dict]:
        return self.history[-n:]

    def is_duplicate(
        self, action: str, params: dict, threshold: float = 0.8
    ) -> bool:
        """检测是否为重复操作。"""
        for item in self.history[-5:]:
            if item["action"] == action:
                if self._similar(item["params"], params) > threshold:
                    return True
        return False
```

## 29.6 工具集注册

```python
# toolsets.py 中注册

COMPUTER_USE_TOOLS = [
    "computer_screenshot",
    "computer_mouse_move",
    "computer_mouse_click",
    "computer_mouse_scroll",
    "computer_key_press",
    "computer_text_input",
    "computer_window_list",
    "computer_window_focus",
    "computer_window_move",
]
```
