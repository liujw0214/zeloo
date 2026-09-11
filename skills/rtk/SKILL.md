---
name: rtk
description: RTK (Rust Token Killer) - 命令行输出压缩工具，节省60-90% bash输出token消耗
platforms: [cli]
toolsets: [terminal]
---

# RTK 技能 (Rust Token Killer)

当用户需要压缩命令行输出、节省token消耗、或需要高效查看git/文件/测试等命令输出时激活本技能。

## 核心功能

RTK 是一个高性能 CLI 代理，在命令输出到达 AI 上下文之前进行过滤和压缩，可节省 **60-90% 的 bash 输出**。

## 支持的命令类型

| 操作 | RTK 处理方式 |
|------|-------------|
| `ls` / `tree` | 树形格式 + 文件计数 |
| `cat` / `read` | 智能读取：签名和结构优先 |
| `grep` / `rg` | 截断长行，按文件分组 |
| `git status` | 紧凑stat格式，按状态分组 |
| `git diff` | 精简上下文，去除头部 |
| `git log` | 仅哈希、作者、标题 |
| `git push/pull/commit` | 一行确认替代完整输出 |
| `pytest` | 仅显示失败，折叠traceback |
| `ruff check` | 按规则和文件分组 |
| `docker ps` | 仅关键字段 |
| `kubectl` | 精简pod/service列表 |

## 常用命令

### 文件操作
```bash
rtk ls .                    # 紧凑目录树
rtk read <file>            # 智能文件读取
rtk find "*.py" .          # 紧凑搜索结果
rtk grep "pattern" .        # 分组搜索结果
```

### Git 操作
```bash
rtk git status              # 紧凑状态
rtk git log -n 10           # 单行提交历史
rtk git diff                # 精简diff
rtk git push               # -> "ok main"
rtk git pull               # -> "ok 3 files +10 -2"
```

### 测试与构建
```bash
rtk pytest                 # Python测试 (-90%)
rtk ruff check             # Python lint (-80%)
rtk cargo test             # Rust测试 (-90%)
rtk cargo build            # Rust构建 (-80%)
```

### 容器
```bash
rtk docker ps               # 紧凑容器列表
rtk docker logs <container> # 去重日志
rtk kubectl pods           # 精简pod列表
```

### Token 节省统计
```bash
rtk gain                   # 节省统计摘要
rtk gain --graph           # 30天ASCII图表
rtk gain --daily           # 每日明细
rtk discover               # 发现节省机会
```

## 使用技巧

### 直接包装命令
任何命令都可以用 `rtk` 包装：
```bash
rtk <any-command>           # 自动压缩输出
```

### 极简模式
```bash
rtk -u <command>           # 进一步压缩（ASCII图标+内联格式）
```

### 错误过滤
```bash
rtk err <command>          # 仅显示错误行
rtk test <command>         # 仅显示测试失败
```

## 全局标志

- `-u, --ultra-compact`: ASCII图标、内联格式（进一步减少输出）
- `-v, --verbose`: 增加详细程度（-v, -vv, -vvv）

## 节省是如何计算的

RTK 削减的是 **bash 输出字节数**，不是直接削减账单。

- bash 输出只是输入 token 的来源之一（还有提示词、对话历史等）
- 输入 token 只是账单的一部分（还有输出 token）
- RTK 按 `字节数 / 4` 估算 token 数

## 注意事项

- RTK 百分比数据可靠，绝对 token 数是近似值
- hook 模式可自动拦截所有 bash 调用（Zeloo 暂不支持自动hook）
- 建议对高频命令（如 git、pytest、ruff）优先使用 rtk 包装
