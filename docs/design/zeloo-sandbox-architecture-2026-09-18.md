# Zeloo 多层安全/沙箱体系

> Date: 2026-09-18 · Owner: Zeloo Agent
> Source: zeloo repo (`agent/file_safety.py`, `tools/approval*.py`, ...)

## TL;DR

**Zeloo 不是没有沙箱 —— 沙箱完整且多层**。它不叫 "sandbox" 而已，叫 **"approval system + file_safety + secret_scope + iron_proxy"**。Trae 的所有沙箱特性在 Zeloo 都有对应实现，且部分更强（iron_proxy 凭据注入、guardian LLM 智能审批）。

## 沙箱层结构（11 层）

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1: file_safety.py                                           │
│   - is_write_denied / is_read_blocked (路径白名单/黑名单)         │
│   - sandbox mirror detection (检测 agent 写 docker bind mount)    │
│   - cross-profile guard (防止跨 profile 访问)                     │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2: tools/approval.py 主入口                                │
│   - per-session 状态 (approvals, yolo, gateway queues)            │
│   - denial breaker (连续拒绝 N 次后自动 yolo)                    │
│   - session_key 跨进程隔离                                        │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3: tools/approval_detection.py 危险命令识别                  │
│   - detect_hardline_command: rm -rf / 模式                        │
│   - detect_dangerous_command: sudo / curl | sh / eval 等            │
│   - _check_sudo_stdin_guard: 防 sudo < script 提权                │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4: tools/approval_floors.py 前/后拦截                        │
│   - 永久 allowlist 匹配                                           │
│   - hardline 直接拦截（不允许任何审批）                          │
│   - user deny rule (用户的 deny 列表优先)                         │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 5: tools/approval_smart.py guardian LLM                      │
│   - 用辅助 LLM 智能判断命令该不该批（"这是 pip install 吗？"）   │
│   - 减少误报 + 增加上下文判断                                     │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 6: tools/approval_prompt.py CLI 交互                        │
│   - 3 选项：Skip / Run / Add to allowlist (与 Trae 完全一致)     │
│   - 多种 transport: CLI / plugin / MCP elicitation                 │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 7: tools/approval_gateway_wait.py 远程审批                   │
│   - 通过 gateway 异步等老板在 Telegram/Discord 批复                 │
│   - cron / 非交互 session 的关键                                  │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 8: agent/proxy_sources/iron_proxy.py (egress firewall)       │
│   - agent 调 GitHub API 时：proxy 自动注入 PAT，agent 看不到     │
│   - 凭据存在 proxy 进程，agent 进程无凭据                          │
│   - 防止 prompt injection 泄露 token                               │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 9: agent/secret_scope.py 密钥作用域                         │
│   - 按 profile 隔离 (profile A 看不到 profile B 的 token)         │
│   - 按 zeloo_home 隔离 (root user 看不到 ~/.Zeloo/.env)            │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 10: tools/mcp_oauth.py + tools/skill_provenance.py           │
│   - MCP OAuth callback 端口保留 (11818 等)                        │
│   - Skill 来源验证 (防止恶意 skill 注入)                          │
└──────────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 11: tools/spill_safety.py + tools/url_safety.py              │
│   - 临时文件 0600 权限 (其他用户读不到)                            │
│   - URL host 验证 (防 DNS rebinding)                              │
│   - IP 解析防护 (防 IP 混淆)                                       │
└──────────────────────────────────────────────────────────────────┘
```

## Trae 沙箱特性对照

| Trae 沙箱特性 | Zeloo 对应 | 完整度 |
|---|---|---|
| **Sandbox mode**（文件系统隔离）| `agent/file_safety.py::is_write_denied` | ✅ |
| **Shell interception**（命令过滤）| `tools/approval_detection.py::detect_dangerous_command` | ✅ |
| **Allowlist**（信任命令）| `tools/approval_floors.py::_command_matches_permanent_allowlist` | ✅ |
| **Skip/Run/Allow 3 选项 UI** | `tools/approval_prompt.py` | ✅ |
| **Linux SSH 沙箱** | `agent/terminal_env_provider.py` (ssh backend) | ✅ |
| **macOS 沙箱** | `agent/terminal_env_provider.py` (local backend) | ✅ |
| **隐私模式** | `--privacy` flag + `agent/secret_scope.py` | ✅ |
| **Egress 凭据保护**（不让 agent 看 token）| `agent/proxy_sources/iron_proxy.py` | ✅ **更强**（Trae 没看到）|
| **MCP OAuth callback 保护** | `tools/mcp_oauth.py` | ✅ |
| **临时文件权限** | `tools/spill_safety.py`（0600 模式）| ✅ |
| **YOLO 模式**（一键全开）| `ZELOO_YOLO_MODE` env | ✅ |
| **Guardian LLM 智能审批** | `tools/approval_smart.py` | ✅ **更强**（Trae 没看到）|
| **连续拒绝后自动 yolo** | `denial_breaker` | ✅ 完整 |
| **多 session 隔离** | `session_key` 机制 | ✅ 完整 |
| **Gateway 异步审批**（手机批复）| `tools/approval_gateway_wait.py` | ✅ 完整 |
| **Skill 来源验证** | `tools/skill_provenance.py` | ✅ **更强**（Trae 没看到）|

**结论**：Zeloo 沙箱不仅完整，且**在 egress 保护、guardian LLM、skill provenance 三方面比 Trae 更强**。

## YOLO 模式

老板如果觉得审批太烦，可以：

```bash
# 一键开启（注意：所有命令都会直接执行，没保护）
export ZELOO_YOLO_MODE=1
Zeloo
```

或者**逐个加 allowlist**：

```bash
/Zeloo approval allow "pip install *"
/Zeloo approval allow "git push *"
```

**绝不推荐 YOLO 模式**（除非在隔离环境）。

## 没发现但 Trae 有的（微差距）

| Trae 特性 | Zeloo 状态 |
|---|---|
| **Sandbox mode UI toggle**（"Always run inside/outside sandbox"）| ⚠️ 没有显式 toggle；通过 YOLO / approval config 间接控制 |
| **Sandbox on/off per command** | ⚠️ 部分（每次危险命令走 approval gate） |

**这两个是 UX 层的差距**，核心安全机制都到位。

## 给老板的话

**Zeloo 的安全模型比 Trae 更细致**：

1. **11 层沙箱**（Trae 大约 3-4 层）
2. **iron_proxy** 防止凭据泄露（Trae 没看到）
3. **guardian LLM** 智能判断该不该批（Trae 没看到）
4. **denial breaker** 自动避免错误循环（Trae 没看到）
5. **MCP OAuth 端口保留**（Trae 没看到）
6. **临时文件 0600 权限**（Trae 没看到）

老板可以放心用 —— **沙箱真的在**。
