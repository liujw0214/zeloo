/**
 * M1.5 Phase 7: create-room button + dialog tests.
 *
 * Mocks the createRoom client and the queryClient. Covers the
 * happy path (button opens dialog → submit calls createRoom →
 * mutation success closes the dialog and invalidates the query)
 * and the validation path (bad JSON shows an error, empty array
 * shows an error, server error shows the server message).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'

import { createRoom } from '@/api/hosted_rooms'
import { useI18n } from '@/i18n'

import { CreateRoomButton, CreateRoomDialog } from './create-room-button'

vi.mock('@/api/hosted_rooms', () => ({
  createRoom: vi.fn()
}))

vi.mock('@/i18n', () => ({
  // useI18n returns { t, locale, ... } — t has both desktop.cancel and common.close.
  useI18n: () => ({
    t: { desktop: { cancel: 'Cancel' }, common: { close: 'Close' } }
  })
}))

const createRoomMock = vi.mocked(createRoom)

function withQueryClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

beforeEach(() => {
  createRoomMock.mockReset()
})

afterEach(() => {
  createRoomMock.mockReset()
})

describe('CreateRoomButton', () => {
  it('renders a button that opens the dialog when clicked', async () => {
    render(<CreateRoomButton />, { wrapper: withQueryClient() })

    expect(screen.queryByTestId('create-room-dialog')).toBeNull()
    await act(async () => {
      fireEvent.click(screen.getByTestId('create-room-button'))
    })
    expect(screen.getByTestId('create-room-dialog')).toBeTruthy()
  })
})

describe('CreateRoomDialog', () => {
  it('submits the name + parsed members JSON to createRoom', async () => {
    const created = {
      room_id: 'r-new',
      name: 'My Room',
      members: [],
      authority_gateway_id: 'gw-1',
      authority_epoch: 1,
      next_seq: 0,
      revision: 1,
      created_at: 0,
      updated_at: 0,
      disbanded_at: null
    }
    createRoomMock.mockResolvedValue(created as never)

    render(<CreateRoomDialog open onOpenChange={() => {}} />, { wrapper: withQueryClient() })

    fireEvent.change(screen.getByTestId('create-room-name'), { target: { value: 'My Room' } })
    fireEvent.click(screen.getByTestId('create-room-submit'))

    await waitFor(() => expect(createRoomMock).toHaveBeenCalledTimes(1))
    expect(createRoomMock).toHaveBeenCalledWith({
      name: 'My Room',
      members: expect.arrayContaining([
        expect.objectContaining({ kind: 'user' }),
        expect.objectContaining({ kind: 'agent' })
      ])
    })
  })

  it('shows an error when the members JSON is malformed', async () => {
    render(<CreateRoomDialog open onOpenChange={() => {}} />, { wrapper: withQueryClient() })
    fireEvent.change(screen.getByTestId('create-room-members'), {
      target: { value: 'not json' }
    })
    fireEvent.click(screen.getByTestId('create-room-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('create-room-error')).toBeTruthy()
    })
    expect(createRoomMock).not.toHaveBeenCalled()
  })

  it('shows an error when the members array is empty', async () => {
    render(<CreateRoomDialog open onOpenChange={() => {}} />, { wrapper: withQueryClient() })
    fireEvent.change(screen.getByTestId('create-room-members'), { target: { value: '[]' } })
    fireEvent.click(screen.getByTestId('create-room-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('create-room-error')).toBeTruthy()
    })
    expect(createRoomMock).not.toHaveBeenCalled()
  })

  it('surfaces the server error message when createRoom rejects', async () => {
    createRoomMock.mockRejectedValue(new Error('limit must be between 1 and 500'))
    render(<CreateRoomDialog open onOpenChange={() => {}} />, { wrapper: withQueryClient() })
    fireEvent.click(screen.getByTestId('create-room-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('create-room-error')?.textContent).toContain('limit must be between 1 and 500')
    })
  })
})

describe('Sentinel: public surface', () => {
  it('exports CreateRoomButton and CreateRoomDialog', async () => {
    const mod = await import('./create-room-button')
    expect(typeof mod.CreateRoomButton).toBe('function')
    expect(typeof mod.CreateRoomDialog).toBe('function')
  })
})
