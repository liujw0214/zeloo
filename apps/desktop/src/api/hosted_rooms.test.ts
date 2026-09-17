/**
 * M1.5 Phase 6: hosted-room API client tests.
 *
 * Mocked ZELOOApi; the contract is the path / method / body shape
 * the gateway REST surface expects. If the gateway changes its
 * routing these tests will fail, surfacing the drift at the
 * call site rather than at the chat mount.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ListRoomsResponse, RoomInfo } from '@/api/hosted_rooms'

import { ZELOOApi } from './client'
import { createRoom, disbandRoom, getRoom, listRooms } from './hosted_rooms'

vi.mock('./client', () => ({
  ZELOOApi: vi.fn()
}))

const ZELOOApiMock = vi.mocked(ZELOOApi)

const sampleRoom: RoomInfo = {
  room_id: 'r-test-1',
  name: 'Test Room',
  members: [
    { member_id: 'user-boss', kind: 'user', display_name: 'Boss' },
    { member_id: 'agent-A', kind: 'agent', display_name: 'Agent A', profile: 'default' },
    { member_id: 'agent-B', kind: 'agent', display_name: 'Agent B', profile: 'default' }
  ],
  authority_gateway_id: 'gw-1',
  authority_epoch: 0,
  next_seq: 0,
  revision: 0,
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
  disbanded_at: null
}

describe('hosted_rooms API client', () => {
  beforeEach(() => {
    ZELOOApiMock.mockReset()
  })

  describe('listRooms', () => {
    it('hits GET /api/hosted_rooms with default pagination', async () => {
      const resp: ListRoomsResponse = { rooms: [sampleRoom], total: 1, limit: 50, offset: 0 }
      ZELOOApiMock.mockResolvedValue(resp as never)

      const result = await listRooms()
      expect(result).toEqual(resp)
      expect(ZELOOApiMock).toHaveBeenCalledTimes(1)
      const call = ZELOOApiMock.mock.calls[0]![0]
      expect(call.path).toBe('/api/hosted_rooms?limit=50&offset=0')
      expect(call.method ?? 'GET').toBe('GET')
    })

    it('passes through caller-supplied limit/offset', async () => {
      ZELOOApiMock.mockResolvedValue({ rooms: [], total: 0, limit: 5, offset: 20 } as never)
      await listRooms({ limit: 5, offset: 20 })
      const call = ZELOOApiMock.mock.calls[0]![0]
      expect(call.path).toBe('/api/hosted_rooms?limit=5&offset=20')
    })
  })

  describe('getRoom', () => {
    it('URL-encodes the room id and uses GET', async () => {
      ZELOOApiMock.mockResolvedValue(sampleRoom as never)
      const result = await getRoom('room with space')
      expect(result).toBe(sampleRoom)
      const call = ZELOOApiMock.mock.calls[0]![0]
      expect(call.path).toBe('/api/hosted_rooms/room%20with%20space')
    })

    it('encodes special characters in the room id', async () => {
      ZELOOApiMock.mockResolvedValue(sampleRoom as never)
      await getRoom('r/with#special?chars')
      const call = ZELOOApiMock.mock.calls[0]![0]
      expect(call.path).toBe('/api/hosted_rooms/r%2Fwith%23special%3Fchars')
    })
  })

  describe('createRoom', () => {
    it('POSTs name + members to /api/hosted_rooms', async () => {
      const created: RoomInfo = { ...sampleRoom, room_id: 'r-new', name: 'New Room' }
      ZELOOApiMock.mockResolvedValue(created as never)
      const result = await createRoom({
        name: 'New Room',
        members: [
          { member_id: 'user-boss', kind: 'user' },
          { member_id: 'agent-A', kind: 'agent' }
        ]
      })
      expect(result).toBe(created)
      const call = ZELOOApiMock.mock.calls[0]![0]
      expect(call.method).toBe('POST')
      expect(call.path).toBe('/api/hosted_rooms')
      expect(call.body).toEqual({
        name: 'New Room',
        members: [
          { member_id: 'user-boss', kind: 'user' },
          { member_id: 'agent-A', kind: 'agent' }
        ]
      })
    })
  })

  describe('disbandRoom', () => {
    it('DELETEs the room by id', async () => {
      ZELOOApiMock.mockResolvedValue({ ok: true } as never)
      const result = await disbandRoom('r-123')
      expect(result).toEqual({ ok: true })
      const call = ZELOOApiMock.mock.calls[0]![0]
      expect(call.method).toBe('DELETE')
      expect(call.path).toBe('/api/hosted_rooms/r-123')
    })
  })
})

describe('Sentinel: API client contract for the chat mount', () => {
  it('exports the four verbs the chat + room UI will call', () => {
    expect(typeof listRooms).toBe('function')
    expect(typeof getRoom).toBe('function')
    expect(typeof createRoom).toBe('function')
    expect(typeof disbandRoom).toBe('function')
  })
})
