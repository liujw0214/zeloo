# 9. 浏览器自动化

> Zeloo 通过统一的浏览器提供者接口让 agent 操作真实网页、抓取数据、与 JavaScript 交互。本文档介绍浏览器集成的设计、可用提供者与使用方式。

## 9.1 浏览器提供者（BrowserProvider）

```python
from browser.base import BrowserProvider, PageSnapshot, CrawlResult
```

所有浏览器提供者继承自 `BrowserProvider` 抽象基类，定义统一的接口：

| 方法 | 作用 |
|------|------|
| `navigate(url, wait_for=None, timeout=30)` | 导航到 URL 并返回 `PageSnapshot` |
| `crawl(url, depth=1, max_pages=10)` | 递归抓取，返回 `CrawlResult` |
| `screenshot(url, full_page=False, format="png")` | 截图，返回 PNG/JPEG 字节 |
| `validate_credentials()` | 校验 API key 是否有效 |

`PageSnapshot` 字段：

```python
url: str
title: str = ""
content: str = ""       # 主内容（Markdown 提取）
html: str = ""          # 原始 HTML（可选）
status_code: int = 200
error: str | None = None
metadata: dict[str, Any]
```

`CrawlResult` 字段：

```python
pages: list[PageSnapshot]
provider: str
crawl_url: str
depth: int
total_pages: int
duration_ms: int
```

---

## 9.2 支持的提供者

### BrowserBase（云端浏览器）

```python
from browser import get_provider

b = get_provider("browserbase")
# 自动读取 BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID 环境变量

snapshot = b.navigate("https://example.com")
print(snapshot.title, snapshot.content)

crawl = b.crawl("https://docs.example.com", depth=2, max_pages=20)
for page in crawl.pages:
    print(page.url, "->", page.title)
```

### Firecrawl（AI 内容抓取）

```python
f = get_provider("firecrawl")  # FIRECRAWL_API_KEY

snapshot = f.navigate("https://docs.example.com")
# 返回 Markdown 提取后的主内容
```

---

## 9.3 注册表与发现

```python
from browser import get_provider, list_providers

print(list_providers())
# ['browserbase', 'firecrawl']

p = get_provider("browserbase")
# 若 provider 不存在返回 None
```

注册自定义提供者：

```python
from browser import register_provider
from browser.base import BrowserProvider

class MyCustomBrowser(BrowserProvider):
    name = "custom"
    # 实现 navigate/crawl/screenshot/validate_credentials ...

register_provider("custom", MyCustomBrowser)
```

---

## 9.4 与 Agent 集成

浏览器功能通过工具自动暴露给 agent：

- `browser_navigate(url)` — 调用 `navigate()`
- `browser_crawl(url, depth=1, max_pages=10)` — 调用 `crawl()`
- `browser_screenshot(url)` — 调用 `screenshot()` 并返回 base64

agent 通过这些工具完成实时网页搜索、表单提交、内容提取等操作。

---

## 9.5 错误处理

| 异常类型 | 触发条件 |
|----------|----------|
| `httpx.RequestError` | 网络错误（连接失败 / 超时） |
| `httpx.HTTPStatusError` | 4xx / 5xx 响应 |
| `ValueError` | URL 不合法、参数缺失 |
| `NotImplementedError` | provider 不支持某功能（如 Firecrawl 的 screenshot） |

所有 `navigate/crawl` 调用应包含在 `try/except` 块中：

```python
from browser import get_provider
try:
    b = get_provider("firecrawl")
    snap = b.navigate(url, timeout=20)
    if snap.error:
        print("scrape failed:", snap.error)
except Exception as exc:
    print("browser error:", exc)
```

---

## 9.6 配置参考

| Provider | 必需环境变量 | 可选 |
|----------|-------------|------|
| browserbase | `BROWSERBASE_API_KEY`、`BROWSERBASE_PROJECT_ID` | — |
| firecrawl | `FIRECRAWL_API_KEY` | — |

API key 也可以通过构造函数显式传入：

```python
get_provider("firecrawl", api_key="fc-...")
```