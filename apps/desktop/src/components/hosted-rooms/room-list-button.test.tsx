/**
 * M1.5 Phase 8: RoomListButton + RoomListDialog tests.
 *
 * Cover the button → dialog open path, the loading/empty/error
 * states of the dialog body, and the copy-id click. The
 * useRoomList hook is mocked so the dialog renders synchronously.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'

import type { ListRoomsResponse, RoomInfo } from '@/api/hosted_rooms'

import { useRoomList } from '@/app/chat/hooks/use-room-list'
import { useI18n } from '@/i18n'

import { RoomListButton, RoomListDialog } from './room-list-button'

vi.mock('@/app/chat/hooks/use-room-list', () => ({
  useRoomList: vi.fn(),
  formatRoomTimestamp: (epoch: number) => (epoch ? '2023-11-14 22:13' : '—'),
  userMemberCount: (room: RoomInfo) => room.members.filter(m => m.kind === 'user').length,
  agentMemberCount: (room: RoomInfo) => room.members.filter(m => m.kind === 'agent' || m.kind === 'sub-agent').length
}))

vi.mock('@/i18n', () => ({
  useI18n: () => ({
    t: { desktop: { cancel: 'Cancel' }, common: { close: 'Close' } }
  })
}))

const useRoomListMock = vi.mocked(useRoomList)

function withQueryClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

const room = (id: string, overrides: Partial<RoomInfo> = {}): RoomInfo => ({
  room_id: id,
  name: `Room ${id}`,
  members: [
    { member_id: 'u', kind: 'user' },
    { member_id: 'a1', kind: 'agent' },
    { member_id: 'a2', kind: 'sub-agent' }
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

beforeEach(() => useRoomListMock.mockReset())
afterEach(() => useRoomListMock.mockReset())

describe('RoomListButton', () => {
  it('opens the dialog when clicked', async () => {
    useRoomListMock.mockReturnValue({
      data: undefined, isLoading: true, isError: false, isFetching: false,
      refetch: vi.fn(), error: null
    } as never)

    render(<RoomListButton />, { wrapper: withQueryClient() })
    expect(screen.queryByTestId('room-list-dialog')).toBeNull()
    await act(async () => {
      fireEvent.click(screen.getByTestId('room-list-button'))
    })
    expect(screen.getByTestId('room-list-dialog')).toBeTruthy()
  })
})

describe('RoomListDialog — render states', () => {
  it('shows a loading state while the query is pending', () => {
    useRoomListMock.mockReturnValue({
      data: undefined, isLoading: true, isError: false, isFetching: false,
      refetch: vi.fn(), error: null
    } as never)
    render(<RoomListDialog open onOpenChange={() => {}} />, { wrapper: withQueryClient() })
    expect(screen.getByText(/Loading/)).toBeTruthy()
  })

  it('shows an empty state when the list is empty', () => {
    useRoomListMock.mockReturnValue({
      data: { rooms: [], total: 0, limit: 100, offset: 0 } as ListRoomsResponse,
      isLoading: false, isError: false, isFetching: false,
      refetch: vi.fn(), error: null
    } as never)
    render(<RoomListDialog open onOpenChange={() => {}} />, { wrapper: withQueryClient() })
    expect(screen.getByTestId('room-list-empty')).toBeTruthy()
  })

  it('shows an error state when the query fails', () => {
    useRoomListMock.mockReturnValue({
      data: undefined, isLoading: false, isError: true, isFetching: false,
      refetch: vi.fn(), error: new Error('network down')
    } as never)
    render(<RoomListDialog open onOpenChange={() => {}} />, { wrapper: withQueryClient() })
    expect(screen.getByTestId('room-list-error')?.textContent).toContain('network down')
  })

  it('renders one row per room with copy button', () => {
    useRoomListMock.mockReturnValue({
      data: {
        rooms: [room('r-1', { name: 'First' }), room('r-2', { name: 'Second' })],
        total: 2, limit: 100, offset: 0
      } as ListRoomsResponse,
      isLoading: false, isError: false, isFetching: false,
      refetch: vi.fn(), error: null
    } as never)
    render(<RoomListDialog open onOpenChange={() => {}} />, { wrapper: withQueryClient() })
    const rows = screen.getAllByTestId('room-list-row')
    expect(rows).toHaveLength(2)
    expect(screen.getByText('First')).toBeTruthy()
    expect(screen.getByText('Second')).toBeTruthy()
  })

  it('clicking the copy button writes the room id to the clipboard and flips the label', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      value: { writeText },
      configurable: true
    })

    useRoomListMock.mockReturnValue({
      data: { rooms: [room('r-xyz')], total: 1, limit: 100, offset: 0 } as ListRoomsResponse,
      isLoading: false, isError: false, isFetching: false,
      refetch: vi.fn(), error: null
    } as never)
    render(<RoomListDialog open onOpenChange={() => {}} />, { wrapper: withQueryClient() })

    await act(async () => {
      fireEvent.click(screen.getByTestId('room-list-copy'))
    })
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('r-xyz'))
    expect(screen.getByTestId('room-list-copy')?.textContent).toBe('Copied')
  })

  it('the refresh button calls refetch', () => {
    const refetch = vi.fn()
    useRoomListMock.mockReturnValue({
      data: { rooms: [], total: 0, limit: 100, offset: 0 } as ListRoomsResponse,
      isLoading: false, isError: false, isFetching: false,
      refetch, error: null
    } as never)
    render(<RoomListDialog open onOpenChange={() => {}} />, { wrapper: withQueryClient() })
    fireEvent.click(screen.getByTestId('room-list-refresh'))
    expect(refetch).toHaveBeenCalledTimes(1)
  })
})

describe('Sentinel: public surface', () => {
  it('exports RoomListButton and RoomListDialog', async () => {
    const mod = await import('./room-list-button')
    expect(typeof mod.RoomListButton).toBe('function')
    expect(typeof mod.RoomListDialog).toBe('function')
  })
})
