/**
 * M1.5 Phase 4: room membership store.
 *
 * Holds a `Record<sessionId, roomId>` map. The `useRoomMembership`
 * hook reads from this store to decide whether a given session is
 * a hosted group-chat room, so the AgentProgressPanel can hide
 * itself for normal single-agent sessions.
 *
 * Phase 4 scope:
 *   - The store + hook + types are wired here.
 *   - The actual population of the map (calling
 *     `listRooms` / `getRoom` from the gateway REST API) is
 *     intentionally a follow-up. The pattern in this codebase
 *     (see apps/desktop/src/store/updates.ts for the cadence)
 *     is to do that in a query hook that hydrates from a query
 *     client and refreshes on a poll / websocket event. Adding
 *     it here would commit us to a refresh strategy before
 *     product has signed off.
 *   - In the meantime, `setRoomMembership(sessionId, roomId)`
 *     and `clearRoomMembership(sessionId)` are the seam. A
 *     future Phase 5 commit wires the query hook to call them.
 *
 * The map is keyed by SESSION id, not room id, because the
 * question the UI asks is "is THIS session a room" — a session
 * belongs to at most one room at a time.
 */
import { map, type MapStore } from 'nanostores'
import { useStore } from '@nanostores/react'

export type RoomId = string

/** Per-session room id, or null if the session is not in a room. */
export type RoomMembership = Record<string, RoomId | null>

const _roomMembership: MapStore<RoomMembership> = map<RoomMembership>({})

/** Exported for tests + advanced use. Prefer the helper functions. */
export const $roomMembership = _roomMembership

/** Direct store access for test setup / future query hooks. */
export function getRoomMembershipStore(): MapStore<RoomMembership> {
  return _roomMembership
}

/**
 * Mark a session as belonging to a hosted room, or `null` to mark it
 * as a non-room session. Idempotent: setting the same value twice is
 * a no-op. Returns true if the store was actually mutated.
 */
export function setRoomMembership(sessionId: string, roomId: RoomId | null): boolean {
  if (!sessionId) return false
  const current = _roomMembership.get()[sessionId] ?? null
  if (current === roomId) return false
  _roomMembership.setKey(sessionId, roomId)
  return true
}

/**
 * Drop the membership record for a session. Called on session close
 * to keep the map from growing without bound.
 */
export function clearRoomMembership(sessionId: string): void {
  if (!sessionId) return
  if (!(_roomMembership.get()[sessionId] !== undefined)) return
  _roomMembership.setKey(sessionId, undefined)
}

/**
 * Synchronous read of the membership for a session. Used by the
 * non-React `agent-progress` handler to know whether the dispatched
 * event is for a room session (so it can decide to forward to a
 * special sink) — this is the one path that does not go through
 * `useRoomMembership`.
 */
export function readRoomMembership(sessionId: string | null | undefined): RoomId | null {
  if (!sessionId) return null
  return _roomMembership.get()[sessionId] ?? null
}

/**
 * React hook: returns the room id for the given session, or null if
 * the session is not in a room.
 *
 * Uses `useStore` on the full map rather than `useSessionSlice` —
 * the membership map is not on the hot-path of streaming events, so
 * the cross-session churn that motivated `useSessionSlice` does not
 * apply. The plain `useStore` is the right call here.
 */
export function useRoomMembership(sessionId: string | null | undefined): RoomId | null {
  const all = useStore(_roomMembership)
  if (!sessionId) return null
  return all[sessionId] ?? null
}
