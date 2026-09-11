# 15. 数据生成与轨迹压缩

## 15.1 概述

`datagen/` 包负责对话轨迹的数据工程化处理：采集原始轨迹、压缩存储成本、为训练数据生成做准备。

## 15.2 架构

```
TurnFinalizer._record_trajectory()
        │
        ▼
zeloo_state.py（原始轨迹持久化）
        │
        ▼
datagen/compress_trajectories.py  ──► 压缩后结构
datagen/extract_trajectories.py   ──► 训练数据导出
datagen/dataloader.py             ──► 训练数据加载器（Trajectory / TrajectoryLoader）
```

## 15.3 轨迹压缩（compress_trajectories.py）

### 15.3.1 设计动机

长对话轨迹直接存储成本高，且含大量冗余 token。压缩策略保留首尾关键信息（用户意图 + 最终结果），对中间轮次做摘要，节省约 70% 存储成本。

### 15.3.2 压缩策略

```
head turns (max_turns_full // 2)  ──► 原文保留
middle turns                         ──► 摘要保留（condensed list）
tail turns (max_turns_full // 2)   ──► 原文保留
```

默认策略：保留首尾各 2 轮原文，中间轮次摘要。

### 15.3.3 核心函数

```python
from datagen.compress_trajectories import (
    compress_trajectory,
    _truncate_turn,
    DEFAULT_MAX_TURNS_FULL,
    DEFAULT_MAX_CHARS_PER_TURN,
)

compressed = compress_trajectory(
    turns=turns_list,
    max_turns_full=4,      # 默认保留 2 头 + 2 尾
    max_chars_per_turn=4000,  # 单轮最大字符数
)
```

### 15.3.4 返回结构

```python
{
    "first_turn": {...},           # 原文（截断后）
    "last_turn": {...},            # 原文（截断后）
    "middle_summary": {
        "turn_count": 10,          # 中间轮次数
        "condensed": [...]         # 摘要后的中间轮次
    },
    "stats": {
        "original_turns": 14,
        "compressed_turns": 4,
        "savings_ratio": 0.71
    }
}
```

### 15.3.5 单轮截断

```python
_truncate_turn(turn, max_chars=4000)
# 将单轮 JSON 序列化后截断到 max_chars
# 防止极端长轮次（如大量工具输出）撑爆存储
```

## 15.4 轨迹导出（extract_trajectories.py）

### 15.4.1 导出格式

支持导出为多种训练数据格式：

```python
from datagen.extract_trajectories import extract_for_training

# 导出为 JSONL（每行一条轨迹）
extract_for_training(
    session_ids=["sess_001", "sess_002"],
    format="jsonl",
    output_path="./training_data.jsonl",
)

# 导出为羊驼/Alpaca 格式
extract_for_training(
    session_ids=["sess_001"],
    format="alpaca",
    output_path="./alpaca_data.json",
)
```

### 15.4.2 导出字段

| 字段 | 说明 |
|------|------|
| `instruction` | 用户消息 |
| `output` | Agent 最终响应 |
| `tool_calls` | 工具调用链（可选） |
| `compressed` | 是否经过压缩 |

## 15.5 与自进化系统的关系

```
TurnFinalizer.finalize()
    │
    ├── _evaluate_memory_nudge()
    ├── _evaluate_skill_nudge()
    ├── _record_trajectory()     ← 原始轨迹写入 DB
    └── _spawn_background_review()
            │
            ▼
    Background Review
            │
            ▼
    Curator/技能固化建议
            │
            ▼
    compress_trajectories.py  ← 定期压缩历史轨迹
```

## 15.6 配置

```yaml
# config.yaml
datagen:
  enabled: true
  compress_threshold_turns: 10     # 超过此轮数自动压缩
  max_chars_per_turn: 4000
  export_format: jsonl             # jsonl / alpaca / sharegpt
  export_dir: ~/.Zeloo/trajectories
```
