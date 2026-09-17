/**
 * M1.5 Phase 6: hosted-room API client.
 *
 * Surface for the Desktop renderer to call the gateway's
 * hosted-rooms REST endpoints. The endpoints themselves live in
 * `gateway/hosted_rooms.py` and are exposed on the existing
 * `ZELOOApi` (see `./client.ts`).
 *
 * Phase 6 scope: list + get + create + disband. The four
 * "primary surface" verbs that zeloo_cli's /room slash command
 * already exposed. The query hook (`useRoomMembership`) reads
 * `listRooms`; the chat Mount in Phase 3.5 will read it on
 * session focus and populate the membership store.
 *
 * The `members` payload is a JSON array of `{ member_id, kind,
 * display_name?, profile?, capabilities? }` objects. We do not
 * re-shape it on the client — the consumer (a future Phase 7
 * room roster panel) reads the same shape the gateway wrote.
 */
import { ZELOOApi } from './client'

export type RoomMember = {
  member_id: string
  kind: 'user' | 'agent' | 'sub-agent' | 'gateway' | 'system'
  display_name?: string
  profile?: string
  capabilities?: string[]
}

export interface RoomInfo {
  room_id: string
  name: string
  members: RoomMember[]
  authority_gateway_id: string
  authority_epoch: number
  next_seq: number
  revision: number
  created_at: number
  updated_at: number
  disbanded_at: number | null
}

export interface ListRoomsResponse {
  rooms: RoomInfo[]
  total: number
  limit: number
  offset: number
}

const LIST_TIMEOUT_MS = 10_000
const MUTATE_TIMEOUT_MS = 10_000

/** Phase 6: list active (non-disbanded) rooms. */
export async function listRooms(options: { limit?: number; offset?: number } = {}): Promise<ListRoomsResponse> {
  const limit = options.limit ?? 50
  const offset = options.offset ?? 0
  return ZELOOApi<ListRoomsResponse>({
    path: `/api/hosted_rooms?limit=${limit}&offset=${offset}`,
    timeoutMs: LIST_TIMEOUT_MS
  })
}

/** Phase 6: get one room by id (full state, including events). */
export async function getRoom(roomId: string): Promise<RoomInfo> {
  return ZELOOApi<RoomInfo>({
    path: `/api/hosted_rooms/${encodeURIComponent(roomId)}`,
    timeoutMs: LIST_TIMEOUT_MS
  })
}

/** Phase 6: create a new room. */
export async function createRoom(input: {
  name: string
  members: Array<Omit<RoomMember, 'kind'> & { kind: RoomMember['kind'] }>
}): Promise<RoomInfo> {
  return ZELOOApi<RoomInfo>({
    path: '/api/hosted_rooms',
    method: 'POST',
    body: input,
    timeoutMs: MUTATE_TIMEOUT_MS
  })
}

/** Phase 6: disband (soft-delete) a room. */
export async function disbandRoom(roomId: string): Promise<{ ok: boolean }> {
  return ZELOOApi<{ ok: boolean }>({
    path: `/api/hosted_rooms/${encodeURIComponent(roomId)}`,
    method: 'DELETE',
    timeoutMs: MUTATE_TIMEOUT_MS
  })
}
