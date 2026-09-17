/**
 * M1.5 Phase 2: agent-progress store tests.
 *
 * Covers the ring-buffer store behind the activity stream UI. Pure unit
 * tests — no React, no gateway.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { RpcEvent } from '@/types/Zeloo'

import {
  $agentProgressActiveSession,
  $agentProgressEvents,
  clearAgentProgress,
  pushAgentProgress,
  type AgentProgressKind,
} from './agent-progress'

function makeEvent(type: string, payload: Record<string, unknown> = {}): RpcEvent {
  return { type, payload, session_id: 'test-session' } as unknown as RpcEvent
}

describe('pushAgentProgress — basic acceptance', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  it.each<AgentProgressKind>([
    'agent.thinking',
    'agent.done',
    'agent.failed',
    'agent.tool',
    'agent.progress',
    'agent.waiting_child',
  ])('accepts %s', (kind) => {
    const entry = pushAgentProgress(makeEvent(kind, { task_id: 't1' }), 'desc', 's1')
    expect(entry).not.toBeNull()
    expect(entry!.kind).toBe(kind)
    expect(entry!.sessionId).toBe('s1')
  })

  it('rejects non-agent events (returns null, no store mutation)', () => {
    const before = $agentProgressEvents.get()
    const entry = pushAgentProgress(makeEvent('message.start', {}), 'desc', 's1')
    expect(entry).toBeNull()
    expect($agentProgressEvents.get()).toBe(before)
  })

  it('rejects empty sessionId', () => {
    expect(pushAgentProgress(makeEvent('agent.thinking'), 'desc', '')).toBeNull()
  })

  it('marks agent.done as terminal=success', () => {
    const entry = pushAgentProgress(makeEvent('agent.done'), 'desc', 's1')
    expect(entry!.terminal).toBe('success')
  })

  it('marks agent.failed as terminal=failure', () => {
    const entry = pushAgentProgress(makeEvent('agent.failed'), 'desc', 's1')
    expect(entry!.terminal).toBe('failure')
  })

  it('marks non-terminal kinds with terminal=null', () => {
    expect(pushAgentProgress(makeEvent('agent.thinking'), '', 's1')!.terminal).toBeNull()
    expect(pushAgentProgress(makeEvent('agent.tool'), '', 's1')!.terminal).toBeNull()
  })
})

describe('pushAgentProgress — ordering and dedupe', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  it('newest entry is at index 0', () => {
    pushAgentProgress(makeEvent('agent.thinking', { event_id: '1' }), 'a', 's1')
    pushAgentProgress(makeEvent('agent.tool', { event_id: '2' }), 'b', 's1')
    pushAgentProgress(makeEvent('agent.done', { event_id: '3' }), 'c', 's1')
    const buf = $agentProgressEvents.get().s1
    expect(buf.map((e) => e.description)).toEqual(['c', 'b', 'a'])
  })

  it('dedupes by event_id (re-emit after reconnect)', () => {
    const e1 = { event_id: 'evt-1', task_id: 't' }
    pushAgentProgress(makeEvent('agent.thinking', e1), 'a', 's1')
    pushAgentProgress(makeEvent('agent.thinking', e1), 'a (retry)', 's1')
    expect($agentProgressEvents.get().s1).toHaveLength(1)
  })

  it('falls back to kind+timestamp for ids when event_id missing', () => {
    pushAgentProgress(makeEvent('agent.thinking', { timestamp: 1700000000 }), 'a', 's1')
    pushAgentProgress(makeEvent('agent.thinking', { timestamp: 1700000000 }), 'b', 's1')
    // Same kind+ts → same id → dedupe keeps 1.
    expect($agentProgressEvents.get().s1).toHaveLength(1)
  })
})

describe('pushAgentProgress — ring buffer cap', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  it('caps at RETAIN_PER_SESSION (32) entries', () => {
    for (let i = 0; i < 50; i++) {
      pushAgentProgress(
        makeEvent('agent.thinking', { event_id: `e-${i}` }),
        `e${i}`,
        's1',
      )
    }
    const buf = $agentProgressEvents.get().s1
    expect(buf).toHaveLength(32)
    // The 32 kept are the most recent (e-49..e-18 in reverse).
    expect(buf[0].description).toBe('e49')
    expect(buf[31].description).toBe('e18')
  })
})

describe('pushAgentProgress — multi-session isolation', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  it('keeps per-session buffers independent', () => {
    pushAgentProgress(makeEvent('agent.thinking', { event_id: 'a1' }), 'in-s1', 's1')
    pushAgentProgress(makeEvent('agent.tool', { event_id: 'a2' }), 'in-s2', 's2')
    expect($agentProgressEvents.get().s1.map((e) => e.description)).toEqual(['in-s1'])
    expect($agentProgressEvents.get().s2.map((e) => e.description)).toEqual(['in-s2'])
  })
})

describe('clearAgentProgress', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  it('removes the session entry', () => {
    pushAgentProgress(makeEvent('agent.thinking', { event_id: '1' }), 'a', 's1')
    clearAgentProgress('s1')
    expect($agentProgressEvents.get().s1).toBeUndefined()
  })

  it('is a no-op when session is unknown', () => {
    const before = $agentProgressEvents.get()
    clearAgentProgress('does-not-exist')
    expect($agentProgressEvents.get()).toBe(before)
  })

  it('rejects empty sessionId', () => {
    pushAgentProgress(makeEvent('agent.thinking'), 'a', 's1')
    const before = $agentProgressEvents.get()
    clearAgentProgress('')
    expect($agentProgressEvents.get()).toBe(before)
  })
})

describe('$agentProgressActiveSession', () => {
  beforeEach(() => {
    $agentProgressActiveSession.set(null)
  })
  afterEach(() => {
    $agentProgressActiveSession.set(null)
  })

  it('starts null and accepts any string', () => {
    expect($agentProgressActiveSession.get()).toBeNull()
    $agentProgressActiveSession.set('s1')
    expect($agentProgressActiveSession.get()).toBe('s1')
  })
})

describe('Sentinel: store API contract must not drift silently', () => {
  it('exports the public surface the dispatcher relies on', () => {
    expect(typeof pushAgentProgress).toBe('function')
    expect(typeof clearAgentProgress).toBe('function')
    expect($agentProgressEvents).toBeDefined()
    expect($agentProgressActiveSession).toBeDefined()
  })
})
