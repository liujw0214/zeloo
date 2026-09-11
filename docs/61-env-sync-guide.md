# 61 · .env 双端同步指南

> 描述 `.env`（项目根）与 `~/.Zeloo/.env`（ZELOO_HOME）双端维护策略。

## 1. 现状

| 位置 | 角色 | 维护者 | 读取方式 |
|------|------|--------|---------|
| `<project>/.env` | 主模板 | Agent | 手动 / 脚本 |
| `~/.Zeloo/.env` | 运行时配置 | 程序 | `zeloo_constants.get_zeloo_home() / .env` |

`zeloo doctor` 的 `env_file` 检查读取的是 `~/.Zeloo/.env`（见 [cli.py:715](cli.py#L715)）。

## 2. 同步策略（两处同时存）

### 2.1 推荐工作流

1. 修改 `<project>/.env`
2. 手动或通过脚本复制到 `~/.Zeloo/.env`

### 2.2 复制脚本（PowerShell）

```powershell
# 复制项目 .env 到 ZELOO_HOME
Copy-Item -Force .env "$env:USERPROFILE\.Zeloo\.env"
```

### 2.3 复制脚本（Bash）

```bash
cp -f .env ~/.Zeloo/.env
```

## 3. 已修正内容

| 项 | 原值 | 修正后 |
|----|------|--------|
| `ZELOO_HOME` | `~/.zeloo`（小写） | `~/.Zeloo`（与 `zeloo_constants.py` 一致） |
| `.env` 第 5 行 | `ZELOO_HOME=~/.zeloo` | `ZELOO_HOME=~/.Zeloo` |
| `.env.example` 第 5 行 | `ZELOO_HOME=~/.zeloo` | `ZELOO_HOME=~/.Zeloo` |

## 4. 待用户手动操作

由于沙箱限制，Agent **不能**写入 `C:\Users\38324\.Zeloo\.env`，请手动执行：

### 4.1 填入 API Key

打开 `~/.Zeloo/.env`（如不存在则从 `<project>/.env` 复制）：

```bash
# 至少填一个（推荐 OPENAI_API_KEY）
OPENAI_API_KEY=sk-your-real-key-here
```

### 4.2 验证

```bash
.venv\Scripts\python.exe -m cli doctor
```

预期输出：
```
[OK] python_version
[OK] zeloo_home
[OK] python_deps
[OK] env_file         .env with API key     ← 修正前是 WARN
```

### 4.3 端到端测试

```bash
.venv\Scripts\python.exe -m cli chat "hello"
```

## 5. 防止两处漂移建议

- CI / 部署脚本统一从 `<project>/.env` 复制到 `~/.Zeloo/.env`
- 修改 `.env` 后立即同步（在 PR 模板里加检查项）
- 或：将来重构 `zeloo_cli.config` 让其同时读两处（项目根优先 → ZELOO_HOME 回退）

## 相关文档

- [docs/10-roadmap.md §10.29](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/10-roadmap.md)
- [docs/60-deployment-scan-report.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/60-deployment-scan-report.md)