# gateway/AGENTS.md

## 本包职责

多平台消息网关：负责接收来自不同平台（Discord/Slack/Telegram/Web 等）的消息，
并将其路由到 Agent 运行时处理。

## 核心模块

- `gateway.py`：网关主调度器
- `voice.py`：语音交互（Console/OpenAI/ElevenLabs TTS + STT）
- `platforms/`：19 个平台适配器（CLI/Web/Discord/Slack/Telegram 等）

## 注意事项

- 网关只负责消息路由，不执行业务逻辑
- 每个平台适配器实现 `PlatformAdapter` 协议
- 所有消息必须经过输入清理（path safety + threat patterns）
- 网关层不应直接访问 Agent 内部状态
