/**
 * M1.5 Phase 5: end-to-end test against the real driver event schema.
 *
 * The M1.1 → M1.5 series was tested only with locally-constructed
 * RpcEvent objects. This test walks the SAME six event kinds the
 * real driver emits (gateway/hosted_room_discussion.py:
 * _PROGRESS_EVENT_FIELDS) through the dispatcher → handler → store
 * pipeline and asserts every one reaches the panel as an entry of
 * the right kind.
 *
 * If a future driver change renames an event, this test will
 * surface the contract drift at the call site rather than as a
 * silent "no panel events" bug at runtime.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { $agentProgressEvents, clearAgentProgress } from '@/store/agent-progress'
import type { RpcEvent } from '@/types/Zeloo'

import { handleAgentProgressEvent } from './agent-progress'
import type { GatewayEventContext } from './types'

function makeContext(event: RpcEvent, sessionId: string | null): GatewayEventContext {
  return {
    deps: {} as GatewayEventContext['deps'],
    event,
    explicitSid: '',
    fromActiveSource: () => true,
    isActiveEvent: true,
    occurredAt: 1_700_000_000,
    payload: event.payload as GatewayEventContext['payload'],
    scheduleConfigRefresh: () => {},
    sessionId,
  }
}

function makeRpcEvent(type: string, payload: Record<string, unknown> = {}): RpcEvent {
  return { type, payload, session_id: 'room-session-1' } as unknown as RpcEvent
}

describe('M1.5 Phase 5: end-to-end pipeline against the real driver schema', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })
  afterEach(() => {
    $agentProgressEvents.set({})
  })

  // The six kinds declared in gateway/hosted_room_discussion.py:
  // _PROGRESS_EVENT_FIELDS — the canonical driver-emit set.
  const realDriverEvents: Array<[string, Record<string, unknown>]> = [
    [
      'agent.thinking',
      {
        task_id: 't-001',
        model: 'MiniMax-M3',
        round: 0,
        thread_id: 'th-1',
        member_id: 'm-1',
        member_index: 0,
        round_index: 0,
        discussion_event_id: 'ev-1',
        turn_id: 'turn-1',
      },
    ],
    [
      'agent.tool_call',
      {
        task_id: 't-001',
        tool: 'read_file',
        call_id: 'c-1',
        round: 0,
        thread_id: 'th-1',
        member_id: 'm-1',
        member_index: 0,
        round_index: 0,
        discussion_event_id: 'ev-2',
        turn_id: 'turn-1',
      },
    ],
    [
      'agent.tool_result',
      {
        task_id: 't-001',
        tool: 'read_file',
        call_id: 'c-1',
        duration_ms: 142,
        status: 'ok',
        thread_id: 'th-1',
        member_id: 'm-1',
        member_index: 0,
        round_index: 0,
        discussion_event_id: 'ev-3',
        turn_id: 'turn-1',
      },
    ],
    [
      'agent.waiting_child',
      {
        task_id: 't-001',
        child_task_id: 't-002',
        child_target: 'sub-agent-B',
        thread_id: 'th-1',
        member_id: 'm-1',
        member_index: 0,
        round_index: 0,
        discussion_event_id: 'ev-4',
        turn_id: 'turn-1',
      },
    ],
    [
      'agent.done',
      {
        task_id: 't-001',
        terminal_kind: 'success',
        tokens: { input: 1024, output: 256 },
        thread_id: 'th-1',
        member_id: 'm-1',
        member_index: 0,
        round_index: 0,
        discussion_event_id: 'ev-5',
        turn_id: 'turn-1',
      },
    ],
    [
      'agent.failed',
      {
        task_id: 't-001',
        error_class: 'ToolTimeout',
        error_message: 'read_file did not return in 60s',
        thread_id: 'th-1',
        member_id: 'm-1',
        member_index: 0,
        round_index: 0,
        discussion_event_id: 'ev-6',
        turn_id: 'turn-1',
      },
    ],
  ]

  it('dispatches all 6 driver-emitted event kinds end-to-end', () => {
    const sessionId = 'room-session-1'
    for (const [kind, payload] of realDriverEvents) {
      const consumed = handleAgentProgressEvent(makeContext(makeRpcEvent(kind, payload), sessionId))
      expect(consumed, `handler did not consume ${kind}`).toBe(true)
    }

    const buf = $agentProgressEvents.get()[sessionId]
    expect(buf).toBeDefined()
    expect(buf).toHaveLength(6)
    // The store keeps each session's ring buffer in newest-first
    // order (pushAgentProgress inserts at index 0). The dispatch
    // order is the driver emit order; the store order is the
    // reverse of that. Reverse for the equality check.
    const kinds = buf!.map(e => e.kind).reverse()
    expect(kinds).toEqual([
      'agent.thinking',
      'agent.tool_call',
      'agent.tool_result',
      'agent.waiting_child',
      'agent.done',
      'agent.failed',
    ])
  })

  it('marks agent.done as terminal=success and agent.failed as terminal=failure', () => {
    const sessionId = 'room-session-1'
    handleAgentProgressEvent(
      makeContext(
        makeRpcEvent('agent.done', { ...realDriverEvents[4][1] }),
        sessionId,
      ),
    )
    handleAgentProgressEvent(
      makeContext(
        makeRpcEvent('agent.failed', { ...realDriverEvents[5][1] }),
        sessionId,
      ),
    )
    const buf = $agentProgressEvents.get()[sessionId]!
    const done = buf.find(e => e.kind === 'agent.done')!
    const failed = buf.find(e => e.kind === 'agent.failed')!
    expect(done.terminal).toBe('success')
    expect(failed.terminal).toBe('failure')
  })

  it('does not consume events that are not in the driver schema (e.g. the old "agent.tool" name)', () => {
    // The historical M1.5 commit 9b41a71a listed 'agent.tool' and
    // 'agent.progress' in AGENT_PROGRESS_EVENT_TYPES. Phase 5
    // removed them because the driver never emits those names.
    // This test pins the removal: if a future commit re-adds
    // 'agent.tool' to the set, the dispatcher would silently
    // accept the wrong event name and the panel would render a
    // 'tool' row that no real room will ever produce.
    const consumed = handleAgentProgressEvent(
      makeContext(makeRpcEvent('agent.tool', { task_id: 't' }), 's'),
    )
    expect(consumed).toBe(false)
    const consumed2 = handleAgentProgressEvent(
      makeContext(makeRpcEvent('agent.progress', { task_id: 't' }), 's'),
    )
    expect(consumed2).toBe(false)
  })

  it('integrates a real room-style sequence (thinking → tool_call → tool_result → done)', () => {
    // Simulate the shape of a single sub-agent doing a read_file
    // then reporting done — what the driver emits for one task in
    // a hosted room.
    const sessionId = 'room-session-1'
    const taskId = 't-readme'

    const evThinking = makeRpcEvent('agent.thinking', { task_id: taskId, model: 'MiniMax-M3', round: 0 })
    const evToolCall = makeRpcEvent('agent.tool_call', { task_id: taskId, tool: 'read_file', call_id: 'c1', round: 0 })
    const evToolResult = makeRpcEvent('agent.tool_result', { task_id: taskId, tool: 'read_file', call_id: 'c1', duration_ms: 50, status: 'ok' })
    const evDone = makeRpcEvent('agent.done', { task_id: taskId, terminal_kind: 'success', tokens: { input: 50, output: 20 } })

    for (const ev of [evThinking, evToolCall, evToolResult, evDone]) {
      expect(handleAgentProgressEvent(makeContext(ev, sessionId))).toBe(true)
    }

    const buf = $agentProgressEvents.get()[sessionId]!
    // Store order is newest-first; reverse for emit-order check.
    expect(buf.map(e => e.kind).reverse()).toEqual([
      'agent.thinking',
      'agent.tool_call',
      'agent.tool_result',
      'agent.done',
    ])
    // descriptions should be human-readable, not raw payloads
    for (const e of buf) {
      expect(typeof e.description).toBe('string')
      expect(e.description.length).toBeGreaterThan(0)
      expect(e.description).not.toMatch(/^\{.*\}$/) // not raw JSON
    }
  })

  it('preserves multi-session isolation in a multi-room setup', () => {
    handleAgentProgressEvent(makeContext(makeRpcEvent('agent.thinking', { task_id: 't-A' }), 'room-A'))
    handleAgentProgressEvent(makeContext(makeRpcEvent('agent.thinking', { task_id: 't-B' }), 'room-B'))
    expect($agentProgressEvents.get()['room-A']).toHaveLength(1)
    expect($agentProgressEvents.get()['room-B']).toHaveLength(1)
    clearAgentProgress('room-A')
    expect($agentProgressEvents.get()['room-A']).toBeUndefined()
    expect($agentProgressEvents.get()['room-B']).toHaveLength(1)
  })
})
