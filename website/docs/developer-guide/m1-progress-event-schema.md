# M1 Event Schema — agent.* progress events

> Status: M1.1 (schema definition only, no behavior change).
> Audit 2026-09-17 / Design: docs/design/m1-implementation-plan-2026-09-17.md §2.

## Overview

This document specifies 6 new event kinds in `hosted_room_events` to expose
member-agent progress in real time. They are emitted by `hosted_room_driver`
during the turn lifecycle (M1.2) and rendered by the TUI (M1.4).

All kinds follow the constraints of `gateway/hosted_rooms.py:48`
(`_EVENT_KIND_RE = ^[a-z][a-z0-9_.-]*$`) and `MAX_EVENT_KIND_CHARS = 64`
(L27). Payloads are JSON-serialized as TEXT (size capped at 256 bytes/event
per design).

## Event kinds

| Kind | When | Payload schema |
|---|---|---|
| `agent.thinking` | turn start, before any tool calls | `{model?: str, prompt_tokens?: int}` |
| `agent.tool_call` | before each tool dispatch | `{tool: str, args_summary: str, call_id: str}` |
| `agent.tool_result` | after tool returns | `{tool: str, call_id: str, status: "ok" \| "err", duration_ms: int}` |
| `agent.waiting_child` | when driver launches a delegate_task subagent | `{subagent_id: str, task: str}` |
| `agent.done` | turn terminal state — success | `{tokens_in: int, tokens_out: int, duration_ms: int}` |
| `agent.failed` | turn terminal state — error | `{error_code: str, error_message: str}` |

## Field constraints

- All string fields: ≤ 200 chars
- All int fields: ≥ 0
- `call_id` MUST be the same string in `agent.tool_call` and its corresponding
  `agent.tool_result`
- `subagent_id` MUST be globally unique within the room
- Payload MUST be JSON-serializable (no datetime, no Path, no bytes)

## Actor convention

All events emitted by `hosted_room_driver` use the same actor JSON as the
existing message.member events (`_actor_for_member` helper). The driver does
NOT introduce a new actor type — agents in a hosted room are already
represented as members.

## Append-only semantics

These events follow the same append-only invariants as `message.member`
(`hosted_rooms.py:101-113`). There is NO update / delete / redact path in
M1. Retraction belongs to a future M (M5 in the design doc).

## Idempotency

Each event has a unique `event_id` derived from:
- For `agent.thinking` / `agent.done` / `agent.failed`: `sha256(member_id +
  attempt_id + kind)[:32]`
- For `agent.tool_call` / `agent.tool_result`: `sha256(call_id + kind +
  duration_ms)[:32]`
- For `agent.waiting_child`: `sha256(subagent_id + kind)[:32]`

Re-emission of the same event_id is rejected by the UNIQUE constraint on
`(room_id, event_id)` (`hosted_rooms.py:111`).

## Cross-gateway protocol compatibility

Adding new event kinds is **forward-compatible** with `hosted_room_replicas`
(gateway sync) since the receiver doesn't care about kind names it doesn't
recognize — it just stores and forwards. `PROTOCOL_VERSION` does NOT need
to bump for this change. (Design plan V3.)

## Throttling

M1 does NOT implement throttling. The 6 kinds are naturally bounded by
turn count (1 thinking + N tool_calls + 1 done per turn). Throttling is
deferred to M3 (steer-with-redirection introduces high-frequency events).