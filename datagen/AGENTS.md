# datagen/AGENTS.md

## 本包职责

数据生成与轨迹压缩，为训练数据生成做准备。

## 核心组件

- `compress_trajectories.py`：轨迹压缩
- `extract_trajectories.py`：训练数据导出

## 轨迹格式

```python
{
    "session_id": "sess_xxx",
    "turn_id": 1,
    "user_message": "...",
    "tool_call_count": 5,
    "tool_calls": [...],
    "assistant_response": "...",
}
```

## 压缩策略

保留首尾轮原文，中间轮次摘要。节省约 70% 存储成本。

## 注意事项

- 轨迹数据不得包含 API 密钥
- 导出数据脱敏后可用于训练
- 压缩后的轨迹仍可还原关键信息