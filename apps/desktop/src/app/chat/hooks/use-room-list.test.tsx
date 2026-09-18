/**
 * M1.5 Phase 8: useRoomList hook tests.
 *
 * Mocks listRooms and pins the query key + refetch behavior. Does
 * NOT exercise the rendering path; the dialog does that.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import type { ListRoomsResponse, RoomInfo } from '@/api/hosted_rooms'
import { listRooms } from '@/api/hosted_rooms'

import {
  agentMemberCount,
  formatRoomTimestamp,
  useRoomList,
  userMemberCount
} from './use-room-list'

vi.mock('@/api/hosted_rooms', () => ({
  listRooms: vi.fn()
}))

const listRoomsMock = vi.mocked(listRooms)

function withQueryClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } }
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

const room = (id: string, overrides: Partial<RoomInfo> = {}): RoomInfo => ({
  room_id: id,
  name: `Room ${id}`,
  members: [
    { member_id: 'user-boss', kind: 'user', display_name: 'Boss' },
    { member_id: 'agent-1', kind: 'agent', display_name: 'Agent 1', profile: 'default' },
    { member_id: 'agent-2', kind: 'sub-agent', display_name: 'Sub 2' }
  ],
  authority_gateway_id: 'gw-1',
  authority_epoch: 0,
  next_seq: 0,
  revision: 0,
  created_at: 1_700_000_000,
  updated_at: 1_700_000_500,
  disbanded_at: null,
  ...overrides
})

beforeEach(() => listRoomsMock.mockReset())
afterEach(() => listRoomsMock.mockReset())

describe('useRoomList', () => {
  it('calls listRooms with limit=100 and resolves with the rows', async () => {
    const resp: ListRoomsResponse = {
      rooms: [room('r-1'), room('r-2')],
      total: 2,
      limit: 100,
      offset: 0
    }
    listRoomsMock.mockResolvedValue(resp as never)
    const { result } = renderHook(() => useRoomList(), { wrapper: withQueryClient() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(listRoomsMock).toHaveBeenCalledWith({ limit: 100 })
    expect(result.current.data?.rooms).toHaveLength(2)
  })

  it('exposes isLoading, isError, and refetch for the dialog to bind to', async () => {
    listRoomsMock.mockResolvedValue({ rooms: [], total: 0, limit: 100, offset: 0 } as never)
    const { result } = renderHook(() => useRoomList(), { wrapper: withQueryClient() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(typeof result.current.refetch).toBe('function')
    expect(result.current.isLoading).toBe(false)
    expect(result.current.isError).toBe(false)
  })

  it('surfaces an error when listRooms rejects', async () => {
    listRoomsMock.mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useRoomList(), { wrapper: withQueryClient() })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBeInstanceOf(Error)
  })
})

describe('formatRoomTimestamp', () => {
  it('formats an epoch as YYYY-MM-DD HH:MM (UTC)', () => {
    // 2023-11-14 22:13:20 UTC == 1700000000
    expect(formatRoomTimestamp(1_700_000_000)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
  })

  it('returns a placeholder for 0 / falsy values', () => {
    expect(formatRoomTimestamp(0)).toBe('—')
  })
})

describe('userMemberCount + agentMemberCount', () => {
  it('counts only kind=user for users', () => {
    expect(userMemberCount(room('r'))).toBe(1)
  })

  it('counts kind=agent + kind=sub-agent for agents', () => {
    expect(agentMemberCount(room('r'))).toBe(2)
  })

  it('returns 0 for a room with no members', () => {
    const empty: RoomInfo = { ...room('r'), members: [] }
    expect(userMemberCount(empty)).toBe(0)
    expect(agentMemberCount(empty)).toBe(0)
  })
})
