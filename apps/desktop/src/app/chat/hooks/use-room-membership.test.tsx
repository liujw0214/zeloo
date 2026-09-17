/**
 * M1.5 Phase 6: useRoomMembership query hook tests.
 *
 * Mocks listRooms and asserts the hook calls it, applies the
 * results to the room-membership store, and skips disbanded rooms.
 * Skips the React Query rendering plumbing; the integration is
 * "hook → effect → store writes", which is what the chat mount
 * actually depends on.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import type { ListRoomsResponse, RoomInfo } from '@/api/hosted_rooms'
import { $roomMembership, readRoomMembership } from '@/store/room-membership'

import { useRoomMembershipQuery } from './use-room-membership'

vi.mock('@/api/hosted_rooms', () => ({
  listRooms: vi.fn()
}))

const listRoomsMock = vi.mocked(await import('@/api/hosted_rooms').then(m => m.listRooms))

// React Query requires a QueryClientProvider ancestor. We make a
// fresh one per test so query state does not leak across tests.
function withQueryClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } }
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

const room = (id: string, opts: Partial<RoomInfo> = {}): RoomInfo => ({
  room_id: id,
  name: `Room ${id}`,
  members: [
    { member_id: 'user-boss', kind: 'user', display_name: 'Boss' }
  ],
  authority_gateway_id: 'gw-1',
  authority_epoch: 0,
  next_seq: 0,
  revision: 0,
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
  disbanded_at: null,
  ...opts
})

beforeEach(() => {
  $roomMembership.set({})
  listRoomsMock.mockReset()
})

afterEach(() => {
  $roomMembership.set({})
})

describe('useRoomMembershipQuery — store wiring', () => {
  it('writes each active room id into the membership store', async () => {
    const resp: ListRoomsResponse = {
      rooms: [room('r-1'), room('r-2'), room('r-3')],
      total: 3, limit: 100, offset: 0
    }
    listRoomsMock.mockResolvedValue(resp)

    renderHook(() => useRoomMembershipQuery(), { wrapper: withQueryClient() })

    await waitFor(() => {
      expect(readRoomMembership('r-1')).toBe('r-1')
      expect(readRoomMembership('r-2')).toBe('r-2')
      expect(readRoomMembership('r-3')).toBe('r-3')
    })
  })

  it('also writes the room as a session key (Phase 7 future seam)', async () => {
    listRoomsMock.mockResolvedValue({
      rooms: [room('r-X')],
      total: 1, limit: 100, offset: 0
    })
    renderHook(() => useRoomMembershipQuery(), { wrapper: withQueryClient() })
    await waitFor(() => {
      expect(readRoomMembership('room:r-X')).toBe('r-X')
    })
  })

  it('skips disbanded rooms (does not write them to the store)', async () => {
    listRoomsMock.mockResolvedValue({
      rooms: [room('r-active'), room('r-old', { disbanded_at: 1_700_000_500 })],
      total: 2, limit: 100, offset: 0
    })
    renderHook(() => useRoomMembershipQuery(), { wrapper: withQueryClient() })
    await waitFor(() => {
      expect(readRoomMembership('r-active')).toBe('r-active')
    })
    // The disbanded room should NOT be in the store
    await act(async () => {})
    expect(readRoomMembership('r-old')).toBeNull()
  })

  it('handles an empty list without throwing', async () => {
    listRoomsMock.mockResolvedValue({ rooms: [], total: 0, limit: 100, offset: 0 })
    renderHook(() => useRoomMembershipQuery(), { wrapper: withQueryClient() })
    await act(async () => {})
    // No rooms to write, store stays empty
    expect(Object.keys($roomMembership.get())).toHaveLength(0)
  })

  it('returns the React Query result so the caller can show loading UI', async () => {
    listRoomsMock.mockResolvedValue({
      rooms: [room('r-1')],
      total: 1, limit: 100, offset: 0
    })
    const { result } = renderHook(() => useRoomMembershipQuery(), { wrapper: withQueryClient() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.rooms).toHaveLength(1)
  })
})

describe('Sentinel: the hook is the single bridge from listRooms to the store', () => {
  it('does not call the gateway REST API more than once per render cycle', async () => {
    listRoomsMock.mockResolvedValue({ rooms: [], total: 0, limit: 100, offset: 0 })
    renderHook(() => useRoomMembershipQuery(), { wrapper: withQueryClient() })
    await waitFor(() => expect(listRoomsMock).toHaveBeenCalledTimes(1))
  })
})
