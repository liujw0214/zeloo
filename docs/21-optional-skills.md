# 21. 可选技能模块（optional_skills）

> ✅ **已集成**：`optional_skills/` 中的函数已通过 `tools/optional_skill_tools.py` 全部注册为 Agent 工具（18 个 `@tool`），纳入 `zeloo_CORE_TOOLS` 和各平台工具集配置。

## 21.1 模块总览

`optional_skills/` 是可选技能的 Python 模块集合，提供专业化 Agent 能力。与内置技能（`skills/` 目录）不同，这些技能通过函数调用方式集成，支持参数化执行和返回值：

```
optional_skills/                # 可选技能 Python 模块
├── __init__.py                # 导出所有技能函数
├── skill_loader.py            # 技能发现与加载（SkillInfo / load_skill_index）
├── software_development.py    # 软件开发技能（code_review / refactor / generate_tests）
├── devops.py                  # DevOps 技能（cicd_analysis / docker_diagnostics / k8s_health）
├── data_science.py            # 数据科学技能（eda / feature_analysis / data_quality_report）
├── mlops.py                   # MLOps 技能
├── research.py                # 研究辅助技能
└── security.py                # 安全技能（dependency_audit / secret_detection / threat_analysis）
```

## 21.2 技能分类

| 模块 | 技能函数 | 说明 |
|------|----------|------|
| `software_development.py` | `code_review()` / `refactor()` / `generate_tests()` | 代码审查、重构建议、测试生成 |
| `devops.py` | `cicd_analysis()` / `docker_diagnostics()` / `k8s_health()` | CI/CD 分析、Docker 诊断、K8s 健康检查 |
| `data_science.py` | `eda()` / `feature_analysis()` / `data_quality_report()` | 探索性数据分析、特征分析、数据质量报告 |
| `mlops.py` | — | 机器学习运维 |
| `research.py` | — | 学术研究辅助 |
| `security.py` | `dependency_audit()` / `secret_detection()` / `threat_analysis()` | 依赖审计、密钥检测、威胁分析 |

## 21.3 技能加载器

`skill_loader.py` 提供技能发现机制，可扫描指定目录下的所有 `SKILL.md` 文件：

```python
from optional_skills.skill_loader import (
    SkillInfo,
    load_skill_index,
    find_skill_by_name,
)

# 扫描 skills 目录，返回所有技能元数据
skills = load_skill_index(Path("~/.Zeloo/skills"))

for skill in skills:
    print(f"{skill.name} ({skill.category})")
    print(f"  描述: {skill.description}")
    print(f"  触发词: {skill.triggers}")
    print(f"  版本: {skill.version}")

# 按名称精确查找
skill = find_skill_by_name("code-review", Path("~/.Zeloo/skills"))
```

**SkillInfo 数据类：**

```python
@dataclass
class SkillInfo:
    name: str           # 技能名称
    category: str       # 所属类别
    description: str    # 技能描述
    triggers: list[str] # 触发词列表
    version: str        # 版本号
    path: Path          # 技能文件路径
```

技能发现机制：
- 扫描 `skill_dir/` 下每个子目录（类别）
- 在每个类别目录下查找 `SKILL.md` 文件
- 解析 frontmatter（`name` / `description` / `version`）
- 从正文 `## Triggers` 段落提取触发词列表

## 21.4 软件开发技能

```python
from optional_skills.software_development import code_review, refactor, generate_tests

# 代码审查（使用 ruff）
result = code_review(code=source_code, language="python", ruff=True)
# result = {"issues": [...], "summary": "...", "severity_counts": {"error": 0, "warning": 1}}

# 重构建议
result = refactor(code=source_code, target="extract_function")
# target: extract_function / simplify_conditionals / remove_duplication / improve_naming
# result = {"suggestions": [...], "summary": "..."}

# 生成测试
result = generate_tests(code=source_code, framework="pytest")
# result = {"test_code": "...", "summary": "..."}
```

## 21.5 DevOps 技能

```python
from optional_skills.devops import cicd_analysis, docker_diagnostics, k8s_health

# CI/CD 流水线分析
result = cicd_analysis(config_path=".github/workflows/ci.yml")
# result = {"issues": [...], "suggestions": [...], "summary": "..."}

# Docker 诊断
result = docker_diagnostics(container_name="Zeloo-app")
# result = {"status": {...}, "logs": [...], "summary": "..."}

# Kubernetes 健康检查
result = k8s_health(namespace="default")
# result = {"pods": [...], "services": [...], "summary": "..."}
```

## 21.6 数据科学生成

```python
from optional_skills.data_science import eda, feature_analysis, data_quality_report

# 探索性数据分析
result = eda(data_path="data.csv", max_rows=10000)
# result = {"stats": {...}, "columns": [...], "types": {...}, "missing": {...}, "summary": "..."}

# 特征分析
result = feature_analysis(data_path="data.csv", target_column="label")
# result = {"correlations": {...}, "importance": {...}, "summary": "..."}

# 数据质量报告
result = data_quality_report(data_path="data.csv")
# result = {"completeness": {...}, "accuracy": {...}, "consistency": {...}, "summary": "..."}
```

## 21.7 安全技能

```python
from optional_skills.security import dependency_audit, secret_detection, threat_analysis

# 依赖审计
result = dependency_audit(requirements_path="requirements.txt")
# result = {"vulnerabilities": [...], "summary": "..."}

# 密钥检测
result = secret_detection(directory=".")
# result = {"secrets": [...], "summary": "..."}

# 威胁分析
result = threat_analysis(code=source_code)
# result = {"threats": [...], "risk_level": "low/medium/high", "summary": "..."}
```

## 21.8 配置启用

```yaml
# config.yaml
skills:
  optional_modules:
    - software_development
    - devops
    - data_science
    - security
```

## 21.9 优先级开发顺序

| 优先级 | 模块 | 技能函数 |
|--------|------|----------|
| P1 | `software_development.py` | `code_review` / `refactor` / `generate_tests` |
| P1 | `devops.py` | `cicd_analysis` / `docker_diagnostics` / `k8s_health` |
| P1 | `data_science.py` | `eda` / `feature_analysis` / `data_quality_report` |
| P1 | `security.py` | `dependency_audit` / `secret_detection` / `threat_analysis` |
| P2 | `mlops.py` | ✅ model_drift_check / training_diagnostics / model_registry_info |
| P2 | `research.py` | ✅ summarize_paper / extract_citations / literature_review |
