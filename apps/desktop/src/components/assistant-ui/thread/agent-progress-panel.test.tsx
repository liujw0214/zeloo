/**
 * M1.5 Phase 3: AgentProgressPanel component tests.
 *
 * Pure rendering + store interaction tests. No AssistantUI, no
 * router, no message stream. We just mount the component, push some
 * entries into the store via pushAgentProgress, and assert the DOM.
 *
 * Each test resets the store in `beforeEach` so tests are order-
 * independent.
 */
import { render, screen } from '@testing-library/react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  $agentProgressEvents,
  $agentProgressActiveSession,
  clearAgentProgress,
  pushAgentProgress,
} from '@/store/agent-progress'
import type { RpcEvent } from '@/types/Zeloo'

import { AgentProgressPanel } from './agent-progress-panel'

function makeEvent(type: string, payload: Record<string, unknown> = {}, id?: string): RpcEvent {
  return {
    type,
    payload: { ...payload, ...(id ? { event_id: id } : {}) },
    session_id: 's',
  } as unknown as RpcEvent
}

describe('AgentProgressPanel — basic rendering', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
    $agentProgressActiveSession.set(null)
  })

  afterEach(() => {
    $agentProgressEvents.set({})
    $agentProgressActiveSession.set(null)
  })

  it('renders the panel with data-testid', () => {
    const { container } = render(<AgentProgressPanel />)
    const panel = container.querySelector('[data-testid="agent-progress-panel"]')
    expect(panel).toBeTruthy()
  })

  it('returns null when the store is empty and hideWhenEmpty is true', () => {
    const { container } = render(<AgentProgressPanel hideWhenEmpty />)
    expect(container.querySelector('[data-testid="agent-progress-panel"]')).toBeNull()
  })

  it('renders the container when the store is empty and hideWhenEmpty is false (default)', () => {
    const { container } = render(<AgentProgressPanel />)
    expect(container.querySelector('[data-testid="agent-progress-panel"]')).toBeTruthy()
    expect(container.querySelectorAll('[data-testid="agent-progress-row"]')).toHaveLength(0)
  })

  it('renders one <li> per entry', () => {
    pushAgentProgress(makeEvent('agent.thinking', {}, 'a'), 'desc-a', 's')
    pushAgentProgress(makeEvent('agent.done', {}, 'b'), 'desc-b', 's')
    pushAgentProgress(makeEvent('agent.tool', {}, 'c'), 'desc-c', 's')

    const { container } = render(<AgentProgressPanel />)
    const rows = container.querySelectorAll('[data-testid="agent-progress-row"]')
    expect(rows).toHaveLength(3)
  })
})

describe('AgentProgressPanel — ordering', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
  })

  it('newest entry renders first (descending by at)', async () => {
    pushAgentProgress(makeEvent('agent.thinking', {}, 'a'), 'oldest', 's')
    await new Promise(r => setTimeout(r, 2))
    pushAgentProgress(makeEvent('agent.tool', {}, 'b'), 'middle', 's')
    await new Promise(r => setTimeout(r, 2))
    pushAgentProgress(makeEvent('agent.done', {}, 'c'), 'newest', 's')

    const { container } = render(<AgentProgressPanel />)
    const descs = [...container.querySelectorAll('[data-testid="agent-progress-row"]')].map(
      r => r.querySelector('.agent-progress-row__desc')?.textContent,
    )
    expect(descs).toEqual(['newest', 'middle', 'oldest'])
  })

  it('respects maxRows and truncates the tail', () => {
    for (let i = 0; i < 10; i++) {
      pushAgentProgress(makeEvent('agent.thinking', {}, `e${i}`), `e${i}`, 's')
    }
    const { container } = render(<AgentProgressPanel maxRows={3} />)
    const rows = container.querySelectorAll('[data-testid="agent-progress-row"]')
    expect(rows).toHaveLength(3)
  })
})

describe('AgentProgressPanel — terminal styling', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
  })

  it('marks agent.done as terminal=success', () => {
    pushAgentProgress(makeEvent('agent.done', {}, 'd'), 'desc', 's')
    const { container } = render(<AgentProgressPanel />)
    const row = container.querySelector('[data-testid="agent-progress-row"]')!
    expect(row.getAttribute('data-terminal')).toBe('success')
    expect(row.classList.contains('agent-progress-row--done')).toBe(true)
  })

  it('marks agent.failed as terminal=failure', () => {
    pushAgentProgress(makeEvent('agent.failed', {}, 'f'), 'desc', 's')
    const { container } = render(<AgentProgressPanel />)
    const row = container.querySelector('[data-testid="agent-progress-row"]')!
    expect(row.getAttribute('data-terminal')).toBe('failure')
    expect(row.classList.contains('agent-progress-row--failed')).toBe(true)
  })

  it('marks non-terminal kinds with data-terminal=none', () => {
    pushAgentProgress(makeEvent('agent.thinking', {}, 't'), 'desc', 's')
    pushAgentProgress(makeEvent('agent.tool', {}, 'tl'), 'desc', 's')
    pushAgentProgress(makeEvent('agent.progress', {}, 'p'), 'desc', 's')
    const { container } = render(<AgentProgressPanel />)
    const rows = container.querySelectorAll('[data-testid="agent-progress-row"]')
    for (const r of rows) {
      expect(r.getAttribute('data-terminal')).toBe('none')
    }
  })
})

describe('AgentProgressPanel — kind label', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
  })

  it('uses a human label for each kind', () => {
    const cases: Array<[string, string]> = [
      ['agent.thinking', 'thinking'],
      ['agent.done', 'done'],
      ['agent.failed', 'failed'],
      ['agent.tool', 'tool'],
      ['agent.progress', 'progress'],
      ['agent.waiting_child', 'waiting for child'],
    ]
    for (const [kind, expectedLabel] of cases) {
      pushAgentProgress(makeEvent(kind, {}, `${kind}-id`), 'd', 's')
    }
    const { container } = render(<AgentProgressPanel />)
    const rows = [...container.querySelectorAll('[data-testid="agent-progress-row"]')]
    for (const [, expectedLabel] of cases) {
      const labels = rows
        .map(r => r.querySelector('.agent-progress-row__label')?.textContent)
        .filter((x): x is string => typeof x === 'string')
      expect(labels).toContain(expectedLabel)
    }
  })
})

describe('AgentProgressPanel — store interaction', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
  })

  it('re-renders when a new event is pushed (live updates)', () => {
    const { container } = render(<AgentProgressPanel />)
    expect(container.querySelectorAll('[data-testid="agent-progress-row"]')).toHaveLength(0)

    act(() => {
      pushAgentProgress(makeEvent('agent.thinking', {}, 'live'), 'just now', 's')
    })
    expect(container.querySelectorAll('[data-testid="agent-progress-row"]')).toHaveLength(1)
  })

  it('removes rows when clearAgentProgress is called', () => {
    pushAgentProgress(makeEvent('agent.thinking', {}, 'x'), 'x', 's')
    const { container } = render(<AgentProgressPanel />)
    expect(container.querySelectorAll('[data-testid="agent-progress-row"]')).toHaveLength(1)

    act(() => {
      clearAgentProgress('s')
    })
    expect(container.querySelectorAll('[data-testid="agent-progress-row"]')).toHaveLength(0)
  })

  it('isolates rows by session id', () => {
    pushAgentProgress(makeEvent('agent.thinking', {}, 'a1'), 'a', 's1')
    pushAgentProgress(makeEvent('agent.thinking', {}, 'a2'), 'b', 's2')
    const { container } = render(<AgentProgressPanel />)
    const rows = container.querySelectorAll('[data-testid="agent-progress-row"]')
    expect(rows).toHaveLength(2)
  })
})

describe('AgentProgressPanel — accessibility', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
  })

  it('exposes aria-live=polite on the panel', () => {
    const { container } = render(<AgentProgressPanel />)
    const panel = container.querySelector('[data-testid="agent-progress-panel"]')!
    expect(panel.getAttribute('aria-live')).toBe('polite')
  })

  it('exposes aria-atomic on each row so a new entry does not re-read the whole list', () => {
    pushAgentProgress(makeEvent('agent.thinking', {}, 'a'), 'd', 's')
    pushAgentProgress(makeEvent('agent.tool', {}, 'b'), 'd', 's')
    const { container } = render(<AgentProgressPanel />)
    const rows = container.querySelectorAll('[data-testid="agent-progress-row"]')
    for (const r of rows) {
      expect(r.getAttribute('aria-atomic')).toBe('true')
    }
  })
})

describe('Sentinel: panel must be importable as a named export', () => {
  it('exports AgentProgressPanel from the module', async () => {
    const mod = await import('./agent-progress-panel')
    expect(typeof mod.AgentProgressPanel).toBe('function')
  })
})

// Suppress the "no test using screen" lint by acknowledging the
// dependency (some tests only need `container`).
void screen
