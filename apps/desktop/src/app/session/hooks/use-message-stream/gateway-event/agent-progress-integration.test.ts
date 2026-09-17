import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { $agentProgressEvents } from '@/store/agent-progress'
import { handleAgentProgressEvent } from './agent-progress'
import type { GatewayEventContext } from './types'

function makeEvent(type: string, payload: Record<string, unknown> = {}): import('@/types/Zeloo').RpcEvent {
  return { type, payload, session_id: 'test-session' } as unknown as import('@/types/Zeloo').RpcEvent
}

function makeContext(event: import('@/types/Zeloo').RpcEvent, sessionId: string | null): GatewayEventContext {
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

describe('Phase 2: handler pushes events into $agentProgressEvents', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  it('writes agent.thinking into the store under ctx.sessionId', () => {
    const event = makeEvent('agent.thinking', { task_id: 't1', model: 'MiniMax-M3' })
    const consumed = handleAgentProgressEvent(makeContext(event, 's-abc'))
    expect(consumed).toBe(true)
    const buf = $agentProgressEvents.get()['s-abc']
    expect(buf).toBeDefined()
    expect(buf).toHaveLength(1)
    expect(buf![0].kind).toBe('agent.thinking')
    expect(buf![0].sessionId).toBe('s-abc')
    expect(buf![0].description).toContain('thinking')
    expect(buf![0].description).toContain('task=t1')
    expect(buf![0].terminal).toBeNull()
  })

  it('does not write when ctx.sessionId is null (unscoped event)', () => {
    const before = JSON.stringify($agentProgressEvents.get())
    handleAgentProgressEvent(makeContext(makeEvent('agent.thinking'), null))
    expect(JSON.stringify($agentProgressEvents.get())).toBe(before)
  })

  it('does not write non-agent events even with a sessionId', () => {
    const before = JSON.stringify($agentProgressEvents.get())
    handleAgentProgressEvent(makeContext(makeEvent('message.start'), 's-1'))
    handleAgentProgressEvent(makeContext(makeEvent('tool.complete'), 's-1'))
    expect(JSON.stringify($agentProgressEvents.get())).toBe(before)
  })

  it('agent.failed entries are tagged terminal=failure', () => {
    handleAgentProgressEvent(
      makeContext(makeEvent('agent.failed', { task_id: 't', error_class: 'OOM' }), 's-1'),
    )
    expect($agentProgressEvents.get()['s-1'][0].terminal).toBe('failure')
  })

  it('handles all 6 kinds without throwing', () => {
    const kinds = [
      'agent.thinking',
      'agent.done',
      'agent.failed',
      'agent.tool',
      'agent.progress',
      'agent.waiting_child',
    ] as const
    for (const kind of kinds) {
      expect(() =>
        handleAgentProgressEvent(makeContext(makeEvent(kind), 's-1')),
      ).not.toThrow()
    }
    expect($agentProgressEvents.get()['s-1']).toHaveLength(6)
  })
})
