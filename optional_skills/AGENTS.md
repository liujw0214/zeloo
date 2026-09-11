# optional-skills/AGENTS.md

## 本包职责

可选技能集（22 类别），默认不启用。用于专业化或较重的技能。

## 与 skills/ 的区别

| 维度 | skills/ | optional-skills/ |
|------|---------|-------------------|
| 启用方式 | 默认启用 | 需在 config.yaml 中显式配置 |
| 体积 | 轻量 | 可能包含额外依赖 |
| 维护 | 随仓库更新 | 可独立发布 |
| 场景 | 通用工作流 | 专业领域 |

## 启用方式

```yaml
skills:
  optional_categories:
    - software-development
    - devops
    - data-science
```

## 注意事项

- 可选技能可能需要额外依赖（如数据库客户端）
- 首次使用前检查依赖是否已安装
- 可选技能由独立仓库维护时，遵循其更新节奏