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
import {
  $roomMembership,
  setRoomMembership,
} from '@/store/room-membership'
import type { RpcEvent } from '@/types/Zeloo'

import { AgentProgressPanel } from './agent-progress-panel'

function makeEvent(type: string, payload: Record<string, unknown> = {}, id?: string): RpcEvent {
  return {
    type,
    payload: { ...payload, ...(id ? { event_id: id } : {}) },
    session_id: 's',
  } as unknown as RpcEvent
}

// Phase 4 added a room-membership gate to AgentProgressPanel. The
// component tests in this file pre-date that gate and were written
// against the "panel is always mounted" contract. They test the
// panel's rendering logic, not the gate, so the helper below
// short-circuits the gate by setting the test session to be a
// known room member. The gate itself has its own test in
// `room-membership.test.ts` (well, the store; the panel-level
// gate is asserted in a separate `describe` block below).
function makeActiveSession(roomId = 'test-room') {
  act(() => {
    $agentProgressActiveSession.set('s')
    setRoomMembership('s', roomId)
  })
}

describe('AgentProgressPanel — basic rendering', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
    $agentProgressActiveSession.set(null)
    $roomMembership.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
    $agentProgressActiveSession.set(null)
    $roomMembership.set({})
  })

  it('renders the panel with data-testid', () => {
    makeActiveSession()
    const { container } = render(<AgentProgressPanel />)
    const panel = container.querySelector('[data-testid="agent-progress-panel"]')
    expect(panel).toBeTruthy()
  })

  it('returns null when the store is empty and hideWhenEmpty is true', () => {
    makeActiveSession()
    const { container } = render(<AgentProgressPanel hideWhenEmpty />)
    expect(container.querySelector('[data-testid="agent-progress-panel"]')).toBeNull()
  })

  it('renders the container when the store is empty and hideWhenEmpty is false (default)', () => {
    makeActiveSession()
    const { container } = render(<AgentProgressPanel />)
    expect(container.querySelector('[data-testid="agent-progress-panel"]')).toBeTruthy()
    expect(container.querySelectorAll('[data-testid="agent-progress-row"]')).toHaveLength(0)
  })

  it('renders one <li> per entry', () => {
    makeActiveSession()
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
    $roomMembership.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
  })

  it('newest entry renders first (descending by at)', async () => {
    makeActiveSession()
    pushAgentProgress(makeEvent('agent.thinking', {}, 'a'), 'oldest', 's')
    await new Promise(r => setTimeout(r, 2))
    pushAgentProgress(makeEvent('agent.tool', {}, 'b'), 'middle', 's')
    await new Promise(r => setTimeout(r, 2))
    pushAgentProgress(makeEvent('agent.done', {}, 'c'), 'newest', 's')

    const { container } = render(<AgentProgressPanel collapsible={false} />)
    const descs = [...container.querySelectorAll('[data-testid="agent-progress-row"]')].map(
      r => r.querySelector('.agent-progress-row__desc')?.textContent,
    )
    expect(descs).toEqual(['newest', 'middle', 'oldest'])
  })

  it('respects maxRows and truncates the tail', () => {
    makeActiveSession()
    for (let i = 0; i < 10; i++) {
      pushAgentProgress(makeEvent('agent.thinking', {}, `e${i}`), `e${i}`, 's')
    }
    const { container } = render(<AgentProgressPanel maxRows={3} collapsible={false} />)
    const rows = container.querySelectorAll('[data-testid="agent-progress-row"]')
    expect(rows).toHaveLength(3)
  })
})

describe('AgentProgressPanel — terminal styling', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
  })

  it('marks agent.done as terminal=success', () => {
    makeActiveSession()
    pushAgentProgress(makeEvent('agent.done', {}, 'd'), 'desc', 's')
    const { container } = render(<AgentProgressPanel collapsible={false} />)
    const row = container.querySelector('[data-testid="agent-progress-row"]')!
    expect(row.getAttribute('data-terminal')).toBe('success')
    expect(row.classList.contains('agent-progress-row--done')).toBe(true)
  })

  it('marks agent.failed as terminal=failure', () => {
    makeActiveSession()
    pushAgentProgress(makeEvent('agent.failed', {}, 'f'), 'desc', 's')
    const { container } = render(<AgentProgressPanel collapsible={false} />)
    const row = container.querySelector('[data-testid="agent-progress-row"]')!
    expect(row.getAttribute('data-terminal')).toBe('failure')
    expect(row.classList.contains('agent-progress-row--failed')).toBe(true)
  })

  it('marks non-terminal kinds with data-terminal=none', () => {
    makeActiveSession()
    pushAgentProgress(makeEvent('agent.thinking', {}, 't'), 'desc', 's')
    pushAgentProgress(makeEvent('agent.tool', {}, 'tl'), 'desc', 's')
    pushAgentProgress(makeEvent('agent.progress', {}, 'p'), 'desc', 's')
    const { container } = render(<AgentProgressPanel collapsible={false} />)
    const rows = container.querySelectorAll('[data-testid="agent-progress-row"]')
    for (const r of rows) {
      expect(r.getAttribute('data-terminal')).toBe('none')
    }
  })
})

describe('AgentProgressPanel — kind label', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
  })

  it('uses a human label for each kind', () => {
    makeActiveSession()
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
    const { container } = render(<AgentProgressPanel collapsible={false} />)
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
    $roomMembership.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
  })

  it('re-renders when a new event is pushed (live updates)', () => {
    makeActiveSession()
    const { container } = render(<AgentProgressPanel collapsible={false} />)
    expect(container.querySelectorAll('[data-testid="agent-progress-row"]')).toHaveLength(0)

    act(() => {
      pushAgentProgress(makeEvent('agent.thinking', {}, 'live'), 'just now', 's')
    })
    expect(container.querySelectorAll('[data-testid="agent-progress-row"]')).toHaveLength(1)
  })

  it('removes rows when clearAgentProgress is called', () => {
    makeActiveSession()
    pushAgentProgress(makeEvent('agent.thinking', {}, 'x'), 'x', 's')
    const { container } = render(<AgentProgressPanel collapsible={false} />)
    expect(container.querySelectorAll('[data-testid="agent-progress-row"]')).toHaveLength(1)

    act(() => {
      clearAgentProgress('s')
    })
    expect(container.querySelectorAll('[data-testid="agent-progress-row"]')).toHaveLength(0)
  })

  it('isolates rows by session id', () => {
    makeActiveSession()
    pushAgentProgress(makeEvent('agent.thinking', {}, 'a1'), 'a', 's1')
    pushAgentProgress(makeEvent('agent.thinking', {}, 'a2'), 'b', 's2')
    const { container } = render(<AgentProgressPanel collapsible={false} />)
    const rows = container.querySelectorAll('[data-testid="agent-progress-row"]')
    expect(rows).toHaveLength(2)
  })
})

describe('AgentProgressPanel — accessibility', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
  })

  it('exposes aria-live=polite on the panel', () => {
    makeActiveSession()
    const { container } = render(<AgentProgressPanel collapsible={false} />)
    const panel = container.querySelector('[data-testid="agent-progress-panel"]')!
    expect(panel.getAttribute('aria-live')).toBe('polite')
  })

  it('exposes aria-atomic on each row so a new entry does not re-read the whole list', () => {
    makeActiveSession()
    pushAgentProgress(makeEvent('agent.thinking', {}, 'a'), 'd', 's')
    pushAgentProgress(makeEvent('agent.tool', {}, 'b'), 'd', 's')
    const { container } = render(<AgentProgressPanel collapsible={false} />)
    const rows = container.querySelectorAll('[data-testid="agent-progress-row"]')
    for (const r of rows) {
      expect(r.getAttribute('aria-atomic')).toBe('true')
    }
  })
})

describe('AgentProgressPanel — Phase 4 room-membership gate', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
    $agentProgressActiveSession.set(null)
  })

  afterEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
    $agentProgressActiveSession.set(null)
  })

  it('returns null when the active session is not in a room', () => {
    pushAgentProgress(makeEvent('agent.thinking', {}, 'x'), 'x', 's')
    act(() => $agentProgressActiveSession.set('s'))
    const { container } = render(<AgentProgressPanel />)
    expect(container.querySelector('[data-testid="agent-progress-panel"]')).toBeNull()
  })

  it('renders when the active session is in a room (the gate opens)', () => {
    pushAgentProgress(makeEvent('agent.thinking', {}, 'x'), 'x', 's')
    act(() => {
      $agentProgressActiveSession.set('s')
      setRoomMembership('s', 'r1')
    })
    const { container } = render(<AgentProgressPanel />)
    expect(container.querySelector('[data-testid="agent-progress-panel"]')).toBeTruthy()
  })

  it('forceShow bypasses the gate (preview screen)', () => {
    pushAgentProgress(makeEvent('agent.thinking', {}, 'x'), 'x', 's')
    act(() => $agentProgressActiveSession.set('s'))
    const { container } = render(<AgentProgressPanel forceShow />)
    expect(container.querySelector('[data-testid="agent-progress-panel"]')).toBeTruthy()
  })

  it('re-renders when membership flips from null to a room', () => {
    pushAgentProgress(makeEvent('agent.thinking', {}, 'x'), 'x', 's')
    act(() => $agentProgressActiveSession.set('s'))
    const { container } = render(<AgentProgressPanel />)
    expect(container.querySelector('[data-testid="agent-progress-panel"]')).toBeNull()

    act(() => setRoomMembership('s', 'r1'))
    expect(container.querySelector('[data-testid="agent-progress-panel"]')).toBeTruthy()
  })
})

describe('AgentProgressPanel — Phase 4 collapsible disclosure', () => {
  beforeEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
  })

  afterEach(() => {
    $agentProgressEvents.set({})
    $roomMembership.set({})
  })

  it('renders a <details open> wrapper by default', () => {
    makeActiveSession()
    pushAgentProgress(makeEvent('agent.thinking', {}, 'x'), 'desc', 's')
    const { container } = render(<AgentProgressPanel />)
    const disclosure = container.querySelector('[data-testid="agent-progress-disclosure"]')
    expect(disclosure?.tagName.toLowerCase()).toBe('details')
    expect(disclosure?.hasAttribute('open')).toBe(true)
  })

  it('exposes a <summary> with the row count', () => {
    makeActiveSession()
    pushAgentProgress(makeEvent('agent.thinking', {}, 'a'), 'a', 's')
    pushAgentProgress(makeEvent('agent.done', {}, 'b'), 'b', 's')
    pushAgentProgress(makeEvent('agent.tool', {}, 'c'), 'c', 's')
    const { container } = render(<AgentProgressPanel />)
    const summary = container.querySelector('[data-testid="agent-progress-summary"]')
    expect(summary?.tagName.toLowerCase()).toBe('summary')
    expect(summary?.textContent).toContain('3')
  })

  it('drops the <details> wrapper when collapsible=false', () => {
    makeActiveSession()
    pushAgentProgress(makeEvent('agent.thinking', {}, 'x'), 'desc', 's')
    const { container } = render(<AgentProgressPanel collapsible={false} />)
    expect(container.querySelector('[data-testid="agent-progress-disclosure"]')).toBeNull()
  })

  it('records the room id on the disclosure element', () => {
    makeActiveSession('room-Z')
    pushAgentProgress(makeEvent('agent.thinking', {}, 'x'), 'desc', 's')
    const { container } = render(<AgentProgressPanel />)
    const disclosure = container.querySelector('[data-testid="agent-progress-disclosure"]')
    expect(disclosure?.getAttribute('data-room-id')).toBe('room-Z')
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
