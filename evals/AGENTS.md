# evals/AGENTS.md

## 本包职责

评测套件，用于验证 Agent 能力的正确性和性能。

## 已实现子模块（5 个）

| 子目录 | 描述 | 状态 |
|--------|------|------|
| `token_counting/` | Token 计费评测（cl100k_base / counter / dataset） | ✅ 已实现 |
| `browser_use/` | 浏览器使用能力（11 工具场景 + 通过率） | ✅ 已实现 |
| `compaction/` | 上下文压缩效果评测（关键词保留率） | ✅ 已实现 |
| `readtool/` | 文件读取工具评测（路径安全 + 内容验证） | ✅ 已实现 |
| `token_accounting/` | Token 计数准确性评测（6 个测试用例） | ✅ 已实现 |

## 子模块 API

每个评测子模块都遵循统一接口：

```python
report = run_cases(...)        # 或 run_scenarios
print(f"通过率: {report.pass_rate}")
save_report(report, "report.json")
```

## 评测执行

```bash
# 单元测试
uv run pytest evals/ -v

# 单独运行某个评测
python -c "from evals.browser_use import run_scenarios, default_scenarios; r = run_scenarios(lambda n,a: {'status': 'ok'}); print(r.passed, '/', r.total)"
```

## 注意事项

- 评测结果应与基准对比，检测回归
- 敏感评测数据脱敏后存储
- 评测失败不阻塞主流程，但需记录
- 报告统一保存为 JSON 格式便于对比分析
