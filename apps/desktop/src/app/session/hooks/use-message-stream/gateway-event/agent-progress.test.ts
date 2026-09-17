/**
 * M1.5 agent.* progress event handler tests.
 *
 * These tests exercise handleAgentProgressEvent in isolation — no
 * React, no nanostores, no gateway. The handler is a pure TS function
 * over a GatewayEventContext; we cover:
 *
 *  - event type filtering (only agent.* events handled)
 *  - describe() output (human-readable summary of payload)
 *  - onAgentProgress delegation (optional callback)
 *  - observer error isolation (one bad observer doesn't break dispatch)
 *  - phase-1 console output (DevTools trail; not asserted on content)
 *
 * For end-to-end event flow tests (gateway → desktop), see
 * apps/desktop/src/store/agent-progress-store.test.ts (follow-up).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RpcEvent } from '@/types/Zeloo'

import {
  handleAgentProgressEvent,
  isAgentProgressEvent,
} from './agent-progress'
import type { GatewayEventContext } from './types'

function makeContext(event: RpcEvent, onAgentProgress?: (e: RpcEvent, d: string) => void): GatewayEventContext {
  return {
    deps: onAgentProgress ? ({ onAgentProgress } as never) : ({} as GatewayEventContext['deps']),
    event,
    explicitSid: '',
    fromActiveSource: () => true,
    isActiveEvent: true,
    occurredAt: 1_700_000_000,
    payload: event.payload as GatewayEventContext['payload'],
    scheduleConfigRefresh: vi.fn(),
    sessionId: 'test-session',
  }
}

function makeEvent(type: string, payload: Record<string, unknown> = {}): RpcEvent {
  return { type, payload, session_id: 'test-session' } as unknown as RpcEvent
}

describe('isAgentProgressEvent', () => {
  it.each([
    'agent.thinking',
    'agent.done',
    'agent.failed',
    'agent.tool',
    'agent.progress',
    'agent.waiting_child',
  ])('returns true for %s', (type) => {
    expect(isAgentProgressEvent(makeEvent(type))).toBe(true)
  })

  it.each([
    'message.start',
    'tool.complete',
    'subagent.thinking',
    'lifecycle.gateway_ready',
    'status.update',
  ])('returns false for non-agent event %s', (type) => {
    expect(isAgentProgressEvent(makeEvent(type))).toBe(false)
  })
})

describe('handleAgentProgressEvent filtering', () => {
  it('returns false for non-agent events (lets other handlers try)', () => {
    const consumed = handleAgentProgressEvent(makeContext(makeEvent('message.start')))
    expect(consumed).toBe(false)
  })

  it.each([
    'agent.thinking',
    'agent.done',
    'agent.failed',
    'agent.tool',
    'agent.progress',
    'agent.waiting_child',
  ])('consumes %s', (type) => {
    const consumed = handleAgentProgressEvent(makeContext(makeEvent(type)))
    expect(consumed).toBe(true)
  })
})

describe('handleAgentProgressEvent onAgentProgress delegation', () => {
  it('invokes the onAgentProgress callback with the event and description', () => {
    const onAgentProgress = vi.fn()
    const event = makeEvent('agent.thinking', {
      task_id: 'task-123',
      model: 'MiniMax-M3',
      round: 3,
    })
    const consumed = handleAgentProgressEvent(makeContext(event, onAgentProgress))
    expect(consumed).toBe(true)
    expect(onAgentProgress).toHaveBeenCalledTimes(1)
    const [passedEvent, description] = onAgentProgress.mock.calls[0]
    expect(passedEvent).toBe(event)
    expect(description).toContain('thinking')
    expect(description).toContain('task=task-123')
    expect(description).toContain('model=MiniMax-M3')
    expect(description).toContain('round=3')
  })

  it('works without onAgentProgress (console trail only)', () => {
    const consumed = handleAgentProgressEvent(
      makeContext(makeEvent('agent.done', { task_id: 't1', terminal_kind: 'success' })),
    )
    expect(consumed).toBe(true)
  })

  it('isolates observer errors: a throwing callback does not break dispatch', () => {
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const onAgentProgress = vi.fn(() => {
      throw new Error('observer boom')
    })
    const consumed = handleAgentProgressEvent(
      makeContext(makeEvent('agent.failed', { task_id: 't1', error_class: 'OOM' }), onAgentProgress),
    )
    // dispatch still returns true
    expect(consumed).toBe(true)
    // observer was called (and threw)
    expect(onAgentProgress).toHaveBeenCalledTimes(1)
    // we logged the failure (not silenced)
    expect(consoleWarn).toHaveBeenCalled()
    consoleWarn.mockRestore()
  })

  it('omits payload fields that are absent (no empty parens)', () => {
    const onAgentProgress = vi.fn()
    handleAgentProgressEvent(
      makeContext(makeEvent('agent.thinking'), onAgentProgress),
    )
    const description = onAgentProgress.mock.calls[0][1] as string
    expect(description).toBe('thinking')
    expect(description).not.toContain('()')
  })

  it('formats agent.failed with error class', () => {
    const onAgentProgress = vi.fn()
    handleAgentProgressEvent(
      makeContext(
        makeEvent('agent.failed', {
          task_id: 't-99',
          error_class: 'RuntimeError',
          error_message: 'out of memory',
        }),
        onAgentProgress,
      ),
    )
    const description = onAgentProgress.mock.calls[0][1] as string
    expect(description).toContain('failed')
    expect(description).toContain('task=t-99')
    expect(description).toContain('error=RuntimeError')
  })

  it('truncates long text fields to <=80 chars of payload content', () => {
    const longText = 'x'.repeat(200)
    const onAgentProgress = vi.fn()
    handleAgentProgressEvent(
      makeContext(
        makeEvent('agent.done', { task_id: 't1', text: longText }),
        onAgentProgress,
      ),
    )
    const description = onAgentProgress.mock.calls[0][1] as string
    // The describe() format is `label (k=v k=v)` — so the value runs up to
    // the closing paren, which means a naive split("text=") catches the ")".
    // Match the value + closing paren, then strip the paren.
    const match = description.match(/text=([^)]{0,200})/)
    expect(match).not.toBeNull()
    const value = match![1]
    // 80 chars of x, not 200.
    expect(value.length).toBe(80)
    expect(value).toBe('x'.repeat(80))
  })
})

describe('handleAgentProgressEvent console output (Phase 1 trail)', () => {
  let consoleDebugSpy: ReturnType<typeof vi.spyOn>
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    consoleDebugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {})
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    consoleDebugSpy.mockRestore()
    consoleErrorSpy.mockRestore()
  })

  it('logs agent.thinking to console.debug', () => {
    handleAgentProgressEvent(makeContext(makeEvent('agent.thinking')))
    expect(consoleDebugSpy).toHaveBeenCalledTimes(1)
    expect(consoleErrorSpy).not.toHaveBeenCalled()
  })

  it('logs agent.failed to console.error (not debug)', () => {
    handleAgentProgressEvent(makeContext(makeEvent('agent.failed')))
    expect(consoleErrorSpy).toHaveBeenCalledTimes(1)
    expect(consoleDebugSpy).not.toHaveBeenCalled()
  })
})
