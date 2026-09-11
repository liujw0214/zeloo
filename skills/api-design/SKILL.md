---
name: api-design
description: REST/GraphQL/tRPC API 设计决策辅助，覆盖路由、版本控制、分页、错误模型与可观测性
platforms: [cli, tui, api]
toolsets: [file, terminal, code_execution]
---

# API Design

辅助设计 REST/GraphQL/tRPC 接口：选型决策、命名与版本约定、错误模型、可观测性、可测试性。

## Triggers（触发条件）

- "design api" / "api design" / "endpoint structure" / "REST design"
- "设计接口" / "API 风格选型" / "路由怎么组织"

## 选型决策树

```
数据形态?
├─ 简单 CRUD、扁平资源     → REST + JSON
├─ 嵌套/关系复杂、客户端多样 → GraphQL
├─ 类型安全、内部调用       → tRPC / gRPC
└─ 高吞吐服务间通信         → gRPC + Protobuf

客户端?
├─ Web (浏览器)           → REST + JSON 或 tRPC
├─ Mobile (弱网、片段化)   → GraphQL
└─ Server-to-server        → gRPC
```

## REST 最佳实践

### 资源命名

- 用**复数名词**：`/users`、`/orders`、`/orders/{id}/items`
- 用**动名词**表示动作：`/users/{id}/activate`（避免纯动词端点）
- 层级不超过 **3 段**：`/orgs/{org}/projects/{project}/issues`
- 资源 ID 用 UUID 或 slug，避免自增暴露业务量

### HTTP 语义

| 状态码 | 用途 |
|---|---|
| 200 | 成功（有返回体） |
| 201 | 创建成功，附 `Location` 头 |
| 204 | 成功无返回体（删除/更新） |
| 400 | 请求参数错误（schema 校验失败） |
| 401 | 未认证 |
| 403 | 已认证但无权限 |
| 404 | 资源不存在 |
| 409 | 状态冲突（重复、版本冲突） |
| 422 | 语义错误（业务校验失败） |
| 429 | 限流 |
| 5xx | 服务端故障，不要带业务细节 |

### 错误响应统一模型

```json
{
  "error": {
    "code": "USER_EMAIL_TAKEN",
    "message": "该邮箱已被注册",
    "details": { "field": "email" },
    "trace_id": "01J9XQ..."
  }
}
```

- `code` 是稳定的机器可读字符串
- `message` 面向用户，可本地化
- `trace_id` 关联服务端日志

### 分页

- **优先 cursor-based**：`?cursor=eyJpZCI6MTIzfQ&limit=20`
- offset 仅用于管理后台或明确需要跳页的场景
- 返回 `next_cursor` 与 `has_more`，不要返回总条数

### 幂等

- POST/PATCH 必须支持 `Idempotency-Key` 头
- 服务端按 key 去重 + TTL（建议 24h）
- 重复请求返回首次结果

### 限流

- 响应头：`X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset`
- 超限 429 并附 `Retry-After`

### 版本控制

| 方案 | 适用 |
|---|---|
| URL 路径 `/v1/` | 公开 API、强隔离 |
| Header `Accept: application/vnd.api+json;v=2` | 同源演化 |
| 查询参数 `?v=2` | 临时实验 |

- 默认走 URL 路径版本
- 老版本给 deprecation 头：`Deprecation: true` + `Sunset: <date>`

### 文档

- 用 OpenAPI 3.1（`openapi.yaml`）作为单一事实源
- CI 中校验 schema 与实现一致（`schemathesis` / `dredd`）
- 所有错误响应必须出现在 spec 里

## GraphQL 模板

```graphql
type User {
  id: ID!
  email: String!
  orders(first: Int = 20, after: String): OrderConnection!
}
type Query {
  user(id: ID!): User
}
type Mutation {
  activateUser(id: ID!): User!
}
```

要点：
- 用 `Connection` 模式分页
- Mutation 必须返回被修改的对象
- 错误用 union：`ActivateUserResult = User | EmailTakenError | NotFoundError`

## tRPC 模板

```typescript
export const userRouter = router({
  get: publicProcedure
    .input(z.object({ id: z.string().uuid() }))
    .query(({ ctx, input }) => ctx.db.user.findUniqueOrThrow({ where: { id: input.id } })),
  activate: protectedProcedure
    .input(z.object({ id: z.string().uuid() }))
    .mutation(async ({ ctx, input }) => { /* ... */ }),
});
```

要点：
- 用 Zod 做输入校验，前后端共享 schema
- procedure 嵌套：`public` / `protected` / `admin`

## 安全清单

- 鉴权：`Authorization: Bearer <jwt>` 或 cookie + CSRF
- HTTPS-only，禁用明文 cookie
- 输入校验在 schema 层，不要散落到 handler
- 输出过滤：禁止反射敏感字段（写 `toPublicDTO()`）
- 审计日志：写操作记录 `actor_id` / `target` / `trace_id`

## 可观测性

- 每个请求一个 `trace_id`，贯穿 header / 日志 / 错误体
- 关键指标：QPS、p50/p95/p99、错误率、上游依赖延迟
- 在 middleware 层打点，不要散落到 handler

## 反模式

| 反模式 | 修正 |
|---|---|
| 用 GET 改数据 | 改 POST/PATCH/DELETE |
| 嵌套过深 `/a/b/c/d/e/f` | 拆资源或换 GraphQL |
| 用 200 包 404 | 用 404 + 错误体 |
| 把 SQL 错误透出 | 5xx + 通用消息，原始进日志 |
| 自定义 session 协议 | 用 JWT / OAuth2 / Paseto |

## Examples

### 设计一个评论 API

```yaml
# OpenAPI 片段
paths:
  /v1/articles/{id}/comments:
    get:
      parameters:
        - in: path
          name: id
          required: true
          schema: { type: string, format: uuid }
        - in: query
          name: cursor
          schema: { type: string }
        - in: query
          name: limit
          schema: { type: integer, default: 20, maximum: 100 }
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  items: { type: array, items: { $ref: '#/components/schemas/Comment' } }
                  next_cursor: { type: string, nullable: true }
                  has_more: { type: boolean }
```

设计要点：cursor 分页、`has_more`、资源嵌套层级合规、UUID。

## 验证

- OpenAPI schema 通过校验
- 至少 1 个 happy-path + 1 个 error-path 的契约测试
- 错误码全部出现在 spec
- 限流与幂等头可观察（集成测试断言）
