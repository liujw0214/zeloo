# Hosted Room Progress Events (M1.1)

> Status: **Implemented** (M1.1, 2026-09-17)  
> Protocol version: unchanged (PROTOCOL_VERSION = 2, backward-compatible)

## Overview

M1.1 adds 6 new `member`-authored event kinds for single-bot progress visibility in group chat.
Events are **append-only** — they are stored in the room event log alongside existing `message.member`
and `turn.*` events, and are returned by `groups.log`. They do **not** break prompt caching
(append-only, not in-system-prompt injection).

## Event Kinds

| kind | actor | Required payload fields | Description |
|---|---|---|---|
| `agent.thinking` | member | `task_id`, `model`, `round` | Member's turn has started; LLM has not spoken yet |
| `agent.tool_call` | member | `task_id`, `tool`, `call_id`, `round` | Tool invocation is about to happen |
| `agent.tool_result` | member | `task_id`, `tool`, `call_id`, `duration_ms`, `status` | Tool returned (`status` = `"ok"` or `"error"`) |
| `agent.waiting_child` | member | `task_id`, `child_task_id`, `child_target` | Subagent delegation in flight |
| `agent.done` | member | `task_id`, `terminal_kind`, `tokens` | Turn finished normally |
| `agent.failed` | member | `task_id`, `error_class`, `error_message` | Turn finished with an error |

## Shared Fields (every progress event)

Every progress event payload carries these turn coordinates, validated by `_validate_turn_coordinates`:

| field | description |
|---|---|
| `task_id` | Driver task identity |
| `thread_id` | Discussion thread |
| `member_id` | Which member |
| `member_index` | Position in room roster |
| `round_index` | Discussion round |

These are required so the frontend can correlate progress events with the correct turn.

## actor Field

Progress events are `member`-authored. The actor must match the member's roster entry:

```python
actor = {
    "kind": "member",
    "id": "<member_id>",        # from room roster
    "profile": "<bot_profile>", # which profile is running this member
    "connection_id": "...",     # gateway-scoped peer id
}
```

## Compatibility

- **PROTOCOL_VERSION**: unchanged (2). Old gateways ignore unknown `agent.*` kinds on receipt
  (peer relay uses `append_event`; no reject-on-unknown-kind logic exists).
- **Append-only**: no existing event format is modified. No schema migration needed.
- **event_id uniqueness**: `UNIQUE (room_id, event_id)` constraint on the events table means
  duplicate emits are rejected — this is the natural deduplication mechanism.
- **Max event kind chars**: `agent.waiting_child` = 19 chars, well under the 64-char limit.

## Append-Only Invariant

Progress events are **not** part of the structured discussion transcript used to build the LLM
prompt. They are stored in the same event log and returned by `groups.log`, but are filtered out
by `_build_prompt` (which only uses `message.user` and `message.member`). This means:

1. Adding a progress event does not change any existing turn's prompt content
2. Prompt caching is fully preserved
3. No new cache-invalidation paths needed

## Schema Validation

`_PROGRESS_EVENT_FIELDS` (`hosted_room_discussion.py`) defines exact + optional fields per kind.
`_validate_progress_event` enforces:
- All required fields present
- Field types correct (`positive_int` for `duration_ms`, `tokens`; `identifier` for `task_id`)
- `agent.tool_result.status` ∈ `{"ok", "error"}`
- `agent.done.terminal_kind` ∈ `{"settled", "failed", "cancelled"}`
- Turn coordinates valid (member exists in roster, indexes in range)

## Future: `groups.capabilities` Extension (M1.4 TUI)

Currently `groups.capabilities` returns a `features` list **without** a `progress_events: true` flag.
M1.4 TUI rendering should add capability detection before rendering progress events:

```python
# M1.4 TUI: before rendering agent.* events, check:
capabilities = groups.capabilities(...)
if "progress_events" not in capabilities.get("features", []):
    # fall back to room.activity status only
    pass
```

## M1.1 Files Changed

| File | Change |
|---|---|
| `gateway/hosted_rooms.py` | `_EVENT_KINDS_BY_ACTOR["member"]` adds 6 new kinds |
| `gateway/hosted_room_discussion.py` | `_PROGRESS_EVENT_FIELDS` dict + `_validate_progress_event` + registration in `_EVENT_VALIDATORS` |

## M1.2 / M1.3: Driver Emit (not in this PR)

M1.2 (driver emit) and M1.3 (tool call emit) will use `hosted_rooms.append_event` with these new
kinds. Hook points:

- `HostedRoomRuntime._publish` (after `admit_task` → `start_task` → session RPC)
- Session RPC callbacks for tool call / tool result
- See `docs/design/m1-implementation-plan-2026-09-17.md §3` for exact insertion points.
