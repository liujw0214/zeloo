# 38. 视频生成模块（video_gen）

本文档介绍 Zeloo 的视频生成（Video Generation）模块，提供统一的抽象接口，支持 3 个主流视频生成 provider。

## 38.1 模块总览

```
video_gen/
├── __init__.py       # 统一导出
├── base.py           # 抽象基类 + 共享类型
├── deepinfra.py      # DeepInfra provider（Hunyuan / Wan 2.1 / Mochi / LTX-Video）
├── fal.py            # FAL.ai provider（Kling / Luma / Hailuo / CogVideoX）
├── xai_video.py      # xAI Grok Video provider
├── registry.py       # provider 注册与发现
└── download.py       # 视频下载工具（持久化输出）
```

## 38.2 快速开始

```python
from video_gen import get_provider, list_providers
from video_gen.download import download_video_result

providers = list_providers()
# ['deepinfra_video', 'fal_video', 'xai_video']

provider = get_provider("deepinfra_video")
resp = provider.generate("A cat sitting on a windowsill")
result = resp.results[0]
print(f"Video URL: {result.url}, 费用: ${result.cost_usd}")

path = download_video_result(result, output_dir="./outputs")
print(f"已保存至: {path}")
```

## 38.3 共享类型（base.py）

### VideoModel（StrEnum）

标准化视频模型标识符，按 provider 分组：

| 成员 | 值 | Provider |
|------|-----|----------|
| `HUNYUAN_VIDEO` | `"hunyuan-video"` | DeepInfra |
| `WAN_2_1` | `"wan-2.1"` | DeepInfra |
| `MOCHI` | `"mochi"` | DeepInfra |
| `LTX_VIDEO` | `"ltx-video"` | DeepInfra |
| `FAL_KLING` | `"fal-kling"` | FAL.ai |
| `FAL_LUMA` | `"fal-luma"` | FAL.ai |
| `FAL_MINIMAX` | `"fal-minimax"` | FAL.ai |
| `XAI_GROK_VIDEO` | `"xai-grok-video"` | xAI |

### VideoResolution（StrEnum）

分辨率预设：

| 成员 | 值 |
|------|-----|
| `SD_480` | `"480p"` |
| `HD_720` | `"720p"` |
| `FHD_1080` | `"1080p"` |
| `LANDSCAPE_1280` | `"1280x720"` |
| `LANDSCAPE_1920` | `"1920x1080"` |
| `PORTRAIT_720` | `"720x1280"` |
| `PORTRAIT_1080` | `"1080x1920"` |
| `SQUARE` | `"1024x1024"` |

### VideoResult

单个生成的视频结果：

```python
@dataclass
class VideoResult:
    url: str                  # 视频文件 URL
    duration_seconds: float   # 时长（秒）
    fps: int                 # 帧率
    width: int               # 宽度（像素）
    height: int              # 高度（像素）
    format: str              # 格式（"mp4", "webm" 等）
    model: str               # 模型标识符
    provider: str             # provider 名称
    cost_usd: float          # 估算费用（USD）
    seed: int | None         # 随机种子（可复现）
    raw: dict[str, Any]      # 原始 API 响应
```

### VideoResponse

Provider `generate()` 的返回值：

```python
@dataclass
class VideoResponse:
    results: list[VideoResult]  # 生成结果列表
    provider: str               # provider 名称
    model: str                  # 使用的模型
    prompt: str                  # 原始 prompt
    cost_usd: float              # 总费用
    request_id: str | None      # API 请求 ID
    raw: dict[str, Any]         # 原始响应
```

## 38.4 Provider 详解

### 38.4.1 DeepInfra（deepinfra.py）

**环境变量**: `DEEPINFRA_API_KEY`

**支持的模型**:

| 模型 | 最大时长 | 最大分辨率 | 定价 |
|------|----------|-----------|------|
| `tencent/HunyuanVideo` | 5s | 1280x720 | $0.30/s |
| `Wan-AI/Wan2.1-T2V-14B` | 6s | 1280x720 | $0.40/s |
| `genmo/mochi-1-preview` | 5.4s | 1280x720 | $0.20/s |
| `Lightricks/LTX-Video` | 5s | 1280x720 | $0.15/s |

> 1080p 分辨率费用加倍。

**使用示例**:

```python
from video_gen.deepinfra import DeepInfraVideoProvider

provider = DeepInfraVideoProvider(api_key="your-key")
resp = provider.generate(
    prompt="A serene mountain landscape at sunset",
    model="tencent/HunyuanVideo",
    resolution="1280x720",
    duration_seconds=5.0,
    seed=42,
)
```

### 38.4.2 FAL.ai（fal.py）

**环境变量**: `FAL_API_KEY`

**支持的模型**:

| 模型 | 最大时长 | 最大分辨率 | 定价 |
|------|----------|-----------|------|
| `fal-ai/kling-video/v1.6/standard/text-to-video` | 10s | 1920x1080 | $0.50/5s |
| `fal-ai/kling-video/v1.5/pro/text-to-video` | 10s | 1920x1080 | - |
| `fal-ai/luma-dream-machine` | 5s | 1280x720 | $0.32/5s |
| `fal-ai/minimax-video-01` | 6s | 1280x720 | $0.28/5s |
| `fal-ai/cogvideox-5b` | 6s | 1280x720 | $0.20/5s |
| `fal-ai/stable-video` | 4s | 1024x576 | $0.15/5s |

> 1080p 分辨率费用加倍。

**使用示例**:

```python
from video_gen.fal import FalVideoProvider

provider = FalVideoProvider(api_key="your-key")
resp = provider.generate(
    prompt="A dog running in a park",
    model="fal-ai/kling-video/v1.6/standard/text-to-video",
    resolution="1920x1080",
    duration_seconds=5.0,
)
```

### 38.4.3 xAI Grok Video（xai_video.py）

**环境变量**: `XAI_API_KEY`

**支持的模型**:

| 模型 | 最大时长 | 最大分辨率 | 定价 |
|------|----------|-----------|------|
| `grok-video-preview` | 10s | 1280x720 | $0.60/5s |
| `grok-2-video` | 8s | 1280x720 | $0.80/5s |

**使用示例**:

```python
from video_gen.xai_video import XaiVideoProvider

provider = XaiVideoProvider(api_key="your-key")
resp = provider.generate(
    prompt="A cat playing piano",
    model="grok-2-video",
    duration_seconds=5.0,
)
```

## 38.5 Provider 注册与发现（registry.py）

```python
from video_gen import get_provider, list_providers, register_provider

# 列出所有注册的 provider
list_providers()  # ['deepinfra_video', 'fal_video', 'xai_video']

# 获取 provider 实例
p = get_provider("deepinfra_video")
# 返回 DeepInfraVideoProvider(api_key=None)

# 注册自定义 provider
class MyVideoProvider(VideoProvider):
    name = "my_video"
    ...

register_provider("my_video", MyVideoProvider)
```

## 38.6 视频下载工具（download.py）

### download_video(url, output_path, ...)

直接下载视频文件：

```python
from video_gen.download import download_video

path = download_video(
    "https://cdn.example.com/video.mp4",
    output_path="./outputs/my_video.mp4",
    timeout=300.0,
)
```

### download_video_result(result, output_dir, ...)

从 `VideoResult` 自动推断文件名并下载：

```python
from video_gen import get_provider
from video_gen.download import download_video_result

provider = get_provider("deepinfra_video")
resp = provider.generate("A cat sitting on a windowsill")
path = download_video_result(resp.results[0], output_dir="./outputs")
# 保存至 ./outputs/A_cat_sitting_on_a_windowsill_s42.mp4
```

**参数说明**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `result` | VideoResult | — | 要下载的视频结果对象 |
| `output_dir` | str/Path | — | 保存目录 |
| `overwrite` | bool | `False` | 目标文件存在时是否覆盖；否则追加 `_1`, `_2` 后缀 |
| `ext` | str | URL 后缀 | 强制文件扩展名 |
| `timeout` | float | 300.0 | 下载超时（秒） |
| `progress_callback` | callable | `None` | 进度回调 `(bytes_done, total)` |

### get_output_path(result, output_dir, ext=None)

生成输出路径（不下载）：

```python
from video_gen.download import get_output_path

path = get_output_path(result, output_dir="./outputs", ext=".webm")
```

### verify_checksum(file_path, expected_sha256)

验证 SHA-256 校验和：

```python
from video_gen.download import verify_checksum

ok = verify_checksum("./video.mp4", "abc123...")
assert ok
```

## 38.7 与 CostTracker 集成

视频生成费用可与 LLM 调用费用一起由 `CostTracker` 统一记录：

```python
from video_gen import get_provider
from agent.cost_tracker import CostTracker

tracker = CostTracker(model="gpt-4o-mini")

# 调用 LLM
tracker.record_usage({"prompt_tokens": 500, "completion_tokens": 200})

# 调用视频生成
provider = get_provider("deepinfra_video")
resp = provider.generate("A cat sitting on a windowsill")
print(f"视频费用: ${resp.cost_usd:.4f}")
# 视频 provider 已估算费用，存储于 VideoResult.cost_usd
# 可通过 tracker.format_cost(currency="CNY") 查看人民币价格
```

## 38.8 与 SessionDB 集成

视频结果可序列化存入 SessionDB 持久化：

```python
import json
from zeloo_state import SessionDB
from video_gen import get_provider

db = SessionDB("state.db")
session_id = "my-session"
db.create_session(session_id=session_id, user_id="u1")

provider = get_provider("deepinfra_video")
resp = provider.generate("A cat sitting on a windowsill")

db.save_message(
    session_id=session_id,
    role="assistant",
    content=json.dumps({"video": resp.results[0].to_dict()}),
)

messages = db.get_messages(session_id, limit=10)
stored = json.loads(messages[-1]["content"])
print(stored["video"]["url"])
```

## 38.9 凭证验证

所有 provider 支持 `validate_credentials()` 方法（无需实际调用 API）：

```python
from video_gen import get_provider

p = get_provider("deepinfra_video")
assert p.validate_credentials()  # api_key 非空且长度 > 8
```

## 38.10 环境变量速查表

| 变量 | Provider | 说明 |
|------|----------|------|
| `DEEPINFRA_API_KEY` | DeepInfra | 从 https://deepinfra.com/dashboard 获取 |
| `FAL_API_KEY` | FAL.ai | 从 https://fal.ai/settings/api-key 获取 |
| `XAI_API_KEY` | xAI | 从 https://console.x.ai 获取 |
