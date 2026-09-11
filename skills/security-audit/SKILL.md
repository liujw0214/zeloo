---
name: security-audit
description: 综合安全审计，串联 secret_scanner + threat_patterns + output_scan，覆盖密钥泄露、注入风险与敏感输出
platforms: [cli, tui, api]
toolsets: [file, terminal, code_execution]
---

# Security Audit

综合安全审计：把密钥扫描、威胁模式检测、输出过滤三个独立工具串联成一条可复用的审计流水线。

## Triggers（触发条件）

- "audit security" / "security check" / "scan vulnerabilities"
- "安全审计" / "扫密钥" / "检测 SQL 注入"

## 工作流程

### 1. 资产清点

- 圈定扫描根目录（默认仓库根），排除 `.venv/`、`node_modules/`、`.git/`
- 收集白名单：`tests/fixtures/`、`docs/`、`.example` 文件
- 记录起点时间，结束时输出 `finished_at`

### 2. 阶段 A：密钥扫描

工具：`secret_scanner.scan_path(path)`

- 检测 API key、密码、token、私钥、数据库连接串
- 规则集：`AKIA*` / `ghp_*` / `xoxb-*` / `-----BEGIN .* PRIVATE KEY-----` / 高熵字符串
- 输出：每条命中含 `file`、`line`、`rule`、`severity`、`snippet`

### 3. 阶段 B：威胁模式

工具：`threat_patterns.analyze(code)`

- 仅对处理用户输入的代码段运行
- 检测模式：
  - SQL 注入（字符串拼接 / 拼接 LIKE）
  - XSS（未转义 HTML 注入）
  - CSRF（缺失 token 校验）
  - 命令注入（`os.system` / `subprocess` + 用户输入）
  - 路径遍历（`open(user_path)` 不做规范化）
  - 不安全反序列化（`pickle.load` / `yaml.load` 不带 `Loader`）

### 4. 阶段 C：输出过滤

工具：`output_scan.filter(data)`

- 对所有把数据写回用户 / 日志的工具做脱敏校验
- 检测：邮箱、手机号、身份证、信用卡、API key、内部 hostname
- 命中即要求上游在写出前打码或省略

### 5. 阶段 D：依赖 CVE

- 解析 `pyproject.toml` / `requirements.txt` / `package.json`
- 与本地 CVE 索引比对（默认用 `safety check` / `npm audit`）
- 标记未固定版本（`>=` / `*`）的高危依赖

### 6. 报告合并

- 按 `file` + `line` 去重
- 严重程度排序：`CRITICAL > HIGH > MEDIUM > LOW`
- 输出统一的 YAML 报告 + Markdown 摘要

## 工具集成

```python
from agent.secret_scanner import scan_path
from tools.threat_patterns import analyze
from tools.output_scan import filter

def audit(root: str) -> dict:
    findings = []
    findings += scan_path(root)
    for f in iter_source(root):
        findings += analyze(f.read_text(), filename=f.name)
    return {"findings": findings, "summary": aggregate(findings)}
```

## 输出格式

```yaml
scan_report:
  started_at: 2026-09-11T10:00:00Z
  finished_at: 2026-09-11T10:03:21Z
  root: .
  findings:
    - scanner: secret
      severity: HIGH
      title: AWS Access Key detected
      location: src/aws.py:42
      suggestion: 改用环境变量 AWS_ACCESS_KEY_ID
    - scanner: threat
      severity: CRITICAL
      title: SQL Injection via string concat
      location: src/users.py:118
      suggestion: 使用参数化查询
    - scanner: output
      severity: MEDIUM
      title: 手机号明文回显
      location: tools/profile.py:55
      suggestion: 用 mask_mobile() 脱敏
summary:
  total: 23
  critical: 2
  high: 5
  medium: 8
  low: 8
```

Markdown 摘要：

```markdown
## Security Audit Summary

| 等级 | 数量 |
|---|---|
| CRITICAL | 2 |
| HIGH | 5 |
| MEDIUM | 8 |
| LOW | 8 |

### Top 修复项
1. `src/aws.py:42` — 硬编码 AKIA*
2. `src/users.py:118` — 字符串拼 SQL
3. `requirements.txt` — unpinned `requests>=2.0`
```

## 注意事项

- **不要把命中原文写进 commit message** 或 PR 描述
- **不要自动 commit 修复**：仅产出报告，由人工 review
- **不要忽略 LOW**：批量 LOW 通常意味着同一种根因
- **白名单要走 PR**：不要本地临时加规则绕过
- 增量扫描：仅跑 `git diff` 范围内的文件可大幅提速

## 严重程度判定

| 等级 | 条件 |
|---|---|
| CRITICAL | 生产密钥、远程 RCE、可直接利用的注入 |
| HIGH | 内部密钥、未授权访问、SSRF |
| MEDIUM | 信息泄露、缺失 rate limit、过期依赖 |
| LOW | 防御深度建议、风格问题 |

## Examples

### 触发方式

- "帮我跑一次安全审计" → 全量扫描
- "只扫这次 PR 的改动" → 增量扫描
- "扫密钥，跳过测试目录" → 仅 secret_scanner + 白名单

### 常见误报抑制

- `.env.example` / `*.example` 内的占位密钥 → 不报
- `tests/` 内的固定 token → 不报
- 文档里以 `<YOUR_KEY>` 形式出现的占位符 → 不报
