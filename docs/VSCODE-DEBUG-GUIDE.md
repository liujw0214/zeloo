# Zeloo VS Code 调试环境配置指南

> 本指南帮助你在 VS Code 中配置 Zeloo 的完整调试环境，包括断点调试、测试运行、lint 检查等。

---

## 目录

1. [环境要求](#1-环境要求)
2. [创建 launch.json](#2-创建-launchjson)
3. [创建 settings.json](#3-创建-settingsjson)
4. [配置说明](#4-配置说明)
5. [使用调试](#5-使用调试)
6. [常见问题](#6-常见问题)

---

## 1. 环境要求

### 1.1 安装扩展

在 VS Code 中安装以下扩展：

| 扩展名称 | ID | 说明 |
|---|---|---|
| **Python** | `ms-python.python` | Python 语言支持 |
| **Ruff** | `charliermarsh.ruff` | Lint + Format（推荐，比 flake8 快 10x）|
| **Pytest** | `pytest-dev.pytest` | pytest 测试支持 |
| **Even Better TOML** | `tamasfe.even-better-toml` | TOML 文件支持 |

### 1.2 Python 环境

确保使用项目虚拟环境：

1. 按 `Ctrl+Shift+P`
2. 输入 `Python: Select Interpreter`
3. 选择 `.venv` 中的 Python

---

## 2. 创建 launch.json

在项目中创建 `.vscode/launch.json` 文件：

```json
{
  "version": "0.2.0",
  "configurations": [
    // ============================================================
    // 交互式 Chat 对话
    // ============================================================
    {
      "name": "Zeloo: Chat",
      "type": "debugpy",
      "request": "launch",
      "module": "cli",
      "args": ["chat"],
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "python": "${workspaceFolder}/.venv/Scripts/python.exe"
    },

    // ============================================================
    // 单次查询（非交互）
    // ============================================================
    {
      "name": "Zeloo: Query",
      "type": "debugpy",
      "request": "launch",
      "module": "cli",
      "args": ["chat", "--query", "Hello, explain what is REST API"],
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "python": "${workspaceFolder}/.venv/Scripts/python.exe"
    },

    // ============================================================
    // TUI 界面
    // ============================================================
    {
      "name": "Zeloo: TUI",
      "type": "debugpy",
      "request": "launch",
      "module": "cli",
      "args": ["tui"],
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "python": "${workspaceFolder}/.venv/Scripts/python.exe"
    },

    // ============================================================
    // Oneshot 快速模式
    // ============================================================
    {
      "name": "Zeloo: Z (Oneshot)",
      "type": "debugpy",
      "request": "launch",
      "module": "cli",
      "args": ["z", "What is 2+2?"],
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "python": "${workspaceFolder}/.venv/Scripts/python.exe"
    },

    // ============================================================
    // Gateway 服务
    // ============================================================
    {
      "name": "Zeloo: Gateway Server",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.run",
      "args": [],
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "python": "${workspaceFolder}/.venv/Scripts/python.exe"
    },

    // ============================================================
    // Web Dashboard
    // ============================================================
    {
      "name": "Zeloo: Dashboard",
      "type": "debugpy",
      "request": "launch",
      "module": "cli",
      "args": ["dashboard"],
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "python": "${workspaceFolder}/.venv/Scripts/python.exe"
    },

    // ============================================================
    // Doctor 诊断
    // ============================================================
    {
      "name": "Zeloo: Doctor",
      "type": "debugpy",
      "request": "launch",
      "module": "cli",
      "args": ["doctor", "--verbose"],
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "python": "${workspaceFolder}/.venv/Scripts/python.exe"
    },

    // ============================================================
    // pytest 当前文件
    // ============================================================
    {
      "name": "Pytest: Current File",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["${file}", "-v", "--tb=short"],
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "python": "${workspaceFolder}/.venv/Scripts/python.exe"
    },

    // ============================================================
    // pytest 全部测试
    // ============================================================
    {
      "name": "Pytest: All Unit Tests",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["tests/unit/", "-v", "--tb=short", "-n", "auto"],
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "python": "${workspaceFolder}/.venv/Scripts/python.exe"
    },

    // ============================================================
    // pytest 指定测试
    // ============================================================
    {
      "name": "Pytest: Selected Test",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": [],
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "python": "${workspaceFolder}/.venv/Scripts/python.exe",
      "presentation": {
        "args": ["tests/unit/test_memory.py::TestMemoryManager::test_add", "-v"]
      }
    },

    // ============================================================
    // Python: 模块（调试脚本）
    // ============================================================
    {
      "name": "Python: Module",
      "type": "debugpy",
      "request": "launch",
      "module": "mymodule",
      "console": "integratedTerminal"
    },

    // ============================================================
    // Python: 当前文件
    // ============================================================
    {
      "name": "Python: Current File",
      "type": "debugpy",
      "request": "launch",
      "program": "${file}",
      "console": "integratedTerminal"
    },

    // ============================================================
    // Attach to Process（附加到进程）
    // ============================================================
    {
      "name": "Python: Attach to Process",
      "type": "debugpy",
      "request": "attach",
      "port": 5678,
      "host": "localhost"
    }
  ],
  "compounds": [
    {
      "name": "Zeloo: All (Chat + Gateway)",
      "configurations": [
        "Zeloo: Gateway Server",
        "Zeloo: Chat"
      ],
      "stopAll": true
    }
  ]
}
```

---

## 3. 创建 settings.json

在项目中创建 `.vscode/settings.json` 文件：

```json
{
  // ============================================================
  // Zeloo Python 开发环境配置
  // ============================================================

  // Python 分析器
  "python.analysis.autoSearchPaths": true,
  "python.analysis.autoImportCompletions": true,
  "python.analysis.diagnosticMode": "workspace",
  "python.analysis.indexing": true,
  "python.analysis.typeCheckingMode": "basic",

  // Python Linting (Ruff)
  "python.linting.enabled": true,
  "python.linting.lintOnSave": true,
  "python.linting.ruffEnabled": true,
  "python.linting.ruffConfigPath": "pyproject.toml",
  "python.linting.ruffCategorySeverity": {
    "E": "Error",
    "W": "Warning",
    "I": "Information",
    "UP": "Hint"
  },

  // Python Formatting (Ruff)
  "python.formatting.provider": "ruff",
  "python.formatting.ruffConfigPath": "pyproject.toml",
  "python.formatting.ruffLineLength": 120,

  // pytest
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": [
    "tests/unit/",
    "-v",
    "--tb=short",
    "--no-header"
  ],
  "python.testing.unittestEnabled": false,
  "python.testing.pytestCwd": "${workspaceFolder}",

  // ============================================================
  // 编辑器配置
  // ============================================================

  // 文件
  "files.associations": {
    "*.md": "markdown",
    "*.yaml": "yaml",
    "*.yml": "yaml",
    ".env*": "dotenv"
  },
  "files.exclude": {
    "**/__pycache__": true,
    "**/*.pyc": true,
    "**/.pytest_cache": true,
    "**/.ruff_cache": true,
    "**/.mypy_cache": true,
    "**/.venv": true,
    "**/*.egg-info": true,
    "**/.git": true
  },
  "files.trimTrailingWhitespace": true,
  "files.insertFinalNewline": true,
  "files.eol": "\n",

  // 编辑器
  "editor.codeActionsOnSave": {
    "source.fixAll": "explicit",
    "source.organizeImports": "explicit"
  },
  "editor.defaultFormatter": "charliermarsh.ruff",
  "editor.formatOnSave": true,
  "editor.formatOnPaste": true,
  "editor.rulers": [88, 120],
  "editor.tabSize": 4,
  "editor.insertSpaces": true,
  "editor.wordWrap": "off",
  "editor.quickSuggestions": {
    "other": true,
    "comments": false,
    "strings": false
  },
  "editor.parameterHints.enabled": true,
  "editor.mouseWheelZoom": true,

  // Python 文件专用
  "[python]": {
    "editor.tabSize": 4,
    "editor.insertSpaces": true,
    "editor.rulers": [88, 120],
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true
  },

  // ============================================================
  // 终端配置
  // ============================================================

  "terminal.integrated.defaultProfile.windows": "PowerShell",
  "terminal.integrated.fontSize": 13,
  "terminal.integrated.cursorBlinking": true,
  "terminal.integrated.scrollback": 10000,

  // ============================================================
  // 探索器配置
  // ============================================================

  "explorer.confirmDelete": false,
  "explorer.confirmDragAndDrop": false,
  "outline.showProperties": true
}
```

---

## 4. 创建 tasks.json（可选）

创建 `.vscode/tasks.json` 用于快捷任务：

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Install Dependencies",
      "type": "shell",
      "command": ".venv\\Scripts\\uv.exe pip install -e .[dev]",
      "cwd": "${workspaceFolder}",
      "problemMatcher": [],
      "group": "none"
    },
    {
      "label": "Run Tests",
      "type": "shell",
      "command": ".venv\\Scripts\\python.exe -m pytest tests/unit/ -v --tb=short",
      "cwd": "${workspaceFolder}",
      "problemMatcher": ["$pytest"],
      "group": {
        "kind": "test",
        "isDefault": true
      }
    },
    {
      "label": "Lint Check",
      "type": "shell",
      "command": ".venv\\Scripts\\ruff.exe check .",
      "cwd": "${workspaceFolder}",
      "problemMatcher": ["$ruff"],
      "group": "none"
    },
    {
      "label": "Format Code",
      "type": "shell",
      "command": ".venv\\Scripts\\ruff.exe format .",
      "cwd": "${workspaceFolder}",
      "problemMatcher": [],
      "group": "none"
    },
    {
      "label": "Doctor Check",
      "type": "shell",
      "command": ".venv\\Scripts\\python.exe -m cli doctor --verbose",
      "cwd": "${workspaceFolder}",
      "problemMatcher": [],
      "group": "none",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      }
    },
    {
      "label": "Lint + Format",
      "type": "shell",
      "command": ".venv\\Scripts\\ruff.exe check --fix . && .venv\\Scripts\\ruff.exe format .",
      "cwd": "${workspaceFolder}",
      "problemMatcher": ["$ruff"],
      "group": "none"
    },
    {
      "label": "Full Quality Check",
      "type": "shell",
      "command": ".venv\\Scripts\\ruff.exe check . && .venv\\Scripts\\ruff.exe format --check . && .venv\\Scripts\\mypy.exe agent/ gateway/ tools/ zeloo_cli/ --ignore-missing-imports",
      "cwd": "${workspaceFolder}",
      "problemMatcher": ["$ruff", "$mypy"],
      "group": "none"
    }
  ]
}
```

---

## 5. 使用调试

### 5.1 快捷键

| 操作 | Windows | macOS |
|---|---|---|
| **开始调试** | `F5` | `F5` |
| **停止调试** | `Shift+F5` | `Shift+F5` |
| **重新开始** | `Ctrl+Shift+F5` | `Cmd+Shift+F5` |
| **断点开/关** | `F9` | `F9` |
| **单步跳过** | `F10` | `F10` |
| **单步进入** | `F11` | `F11` |
| **单步跳出** | `Shift+F11` | `Shift+F11` |
| **运行到断点** | `Ctrl+F10` | `Cmd+F10` |

### 5.2 调试面板

按 `Ctrl+Shift+D` 打开调试面板，选择配置后按 `F5` 开始。

### 5.3 断点调试

在代码中设置断点：

```python
# agent/conversation_loop.py
def run(self, query: str):
    response = self._call_llm(query)  # ← 在这里按 F9 设置断点
    return response
```

### 5.4 条件断点

1. 右键点击断点
2. 选择 **Edit Breakpoint**
3. 输入条件，例如：`iteration > 5`

### 5.5 日志点

1. 右键断点
2. 选择 **Log to Console**
3. 输入：`Iteration: {iteration}`

---

## 6. 常见问题

### Q1: 找不到 Python 解释器

```bash
# 1. 在项目根目录创建虚拟环境
uv venv

# 2. 安装依赖
uv pip install -e ".[dev]"

# 3. 在 VS Code 中按 Ctrl+Shift+P
# 4. 输入 "Python: Select Interpreter"
# 5. 选择 ".venv"
```

### Q2: Ruff 报错找不到配置

确保 `pyproject.toml` 存在于项目根目录：

```json
// settings.json
"python.linting.ruffConfigPath": "${workspaceFolder}/pyproject.toml"
```

### Q3: pytest 找不到测试

```json
// settings.json
"python.testing.pytestArgs": [
    "tests/unit/",
    "-v",
    "--tb=short",
    "--no-header",
    "--rootdir=${workspaceFolder}"
]
```

### Q4: 无法附加到进程

确保目标进程以调试模式启动：

```python
import debugpy
debugpy.listen(("localhost", 5678))
# 等待连接
debugpy.wait_for_client()
```

### Q5: 调试时环境变量不生效

检查 `launch.json` 中的 `env` 配置是否正确：

```json
"env": {
    "ZELOO_ENV": "development",
    "ZELOO_HOME": "${workspaceFolder}/.zeloo-test"
}
```

---

## 7. 推荐工作流

### 7.1 开发新功能

```
1. Ctrl+Shift+P → "Python: Select Interpreter" → 选择 .venv
2. 打开测试文件，按 F5 开始调试
3. 设置断点，查看变量值
4. 修改代码，Ruff 自动格式化
5. 提交前运行 "Lint + Format"
```

### 7.2 修复 Bug

```
1. 找到对应测试文件
2. 选择 "Pytest: Current File" 配置
3. 设置断点在问题代码处
4. 运行测试，观察变量
5. 修复后验证测试通过
```

### 7.3 调试 Gateway

```
1. 选择 "Zeloo: Gateway Server" 配置
2. F5 启动 Gateway
3. 打开浏览器访问 http://localhost:9113
4. 在 VS Code 中设置 API 断点
5. 发送请求，观察响应
```

---

## 8. 完整配置清单

| 文件 | 路径 | 说明 |
|---|---|---|
| launch.json | `.vscode/launch.json` | 调试配置 |
| settings.json | `.vscode/settings.json` | 工作区设置 |
| tasks.json | `.vscode/tasks.json` | 快捷任务 |

请手动在 VS Code 中创建这些文件（`.vscode` 目录可能在 OneDrive 同步时受限）。
