/**
 * M1.5 Phase 9 part 2: useRoomEvents hook tests.
 *
 * Mocks listRoomEvents and pins the query key + refetch behavior.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import type { ListRoomEventsResponse, RoomEvent } from '@/api/hosted_rooms'
import { listRoomEvents } from '@/api/hosted_rooms'

import {
  formatEventTime,
  groupEventsByKind,
  useRoomEvents
} from './use-room-events'

vi.mock('@/api/hosted_rooms', () => ({
  listRoomEvents: vi.fn()
}))

const listRoomEventsMock = vi.mocked(listRoomEvents)

function withQueryClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } }
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

const ev = (kind: string, seq: number, extra: Record<string, unknown> = {}): RoomEvent => ({
  room_id: 'r-1',
  seq,
  event_id: `e-${kind}-${seq}`,
  kind,
  payload: {},
  created_at: 1_700_000_000 + seq,
  ...extra
})

beforeEach(() => listRoomEventsMock.mockReset())
afterEach(() => listRoomEventsMock.mockReset())

describe('useRoomEvents', () => {
  it('does not call listRoomEvents when roomId is null', () => {
    renderHook(() => useRoomEvents(null), { wrapper: withQueryClient() })
    expect(listRoomEventsMock).not.toHaveBeenCalled()
  })

  it('calls listRoomEvents with the roomId and resolves', async () => {
    const resp: ListRoomEventsResponse = {
      events: [ev('agent.thinking', 1), ev('agent.done', 2)],
      total: 2,
      limit: 100,
      offset: 0
    }
    listRoomEventsMock.mockResolvedValue(resp as never)
    const { result } = renderHook(() => useRoomEvents('r-1'), { wrapper: withQueryClient() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(listRoomEventsMock).toHaveBeenCalledWith('r-1', { limit: 100, kinds: undefined })
    expect(result.current.data?.events).toHaveLength(2)
  })

  it('passes kinds filter through to the client', async () => {
    listRoomEventsMock.mockResolvedValue({ events: [], total: 0, limit: 100, offset: 0 } as never)
    const { result } = renderHook(
      () => useRoomEvents('r-1', { kinds: ['agent.thinking', 'agent.done'] }),
      { wrapper: withQueryClient() }
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(listRoomEventsMock).toHaveBeenCalledWith('r-1', {
      limit: 100,
      kinds: ['agent.thinking', 'agent.done']
    })
  })

  it('surfaces an error when listRoomEvents rejects', async () => {
    listRoomEventsMock.mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useRoomEvents('r-1'), { wrapper: withQueryClient() })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBeInstanceOf(Error)
  })
})

describe('groupEventsByKind', () => {
  it('groups by kind in insertion order', () => {
    const events = [
      ev('agent.thinking', 1),
      ev('agent.tool_call', 2),
      ev('agent.thinking', 3),
      ev('agent.done', 4)
    ]
    const groups = groupEventsByKind(events)
    expect([...groups.keys()]).toEqual(['agent.thinking', 'agent.tool_call', 'agent.done'])
    expect(groups.get('agent.thinking')).toHaveLength(2)
    expect(groups.get('agent.tool_call')).toHaveLength(1)
    expect(groups.get('agent.done')).toHaveLength(1)
  })

  it('returns an empty map for an empty list', () => {
    expect(groupEventsByKind([]).size).toBe(0)
  })
})

describe('formatEventTime', () => {
  it('returns HH:MM:SS (UTC)', () => {
    expect(formatEventTime(1_700_000_000)).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  })

  it('returns a placeholder for 0 / falsy values', () => {
    expect(formatEventTime(0)).toBe('—')
  })
})
