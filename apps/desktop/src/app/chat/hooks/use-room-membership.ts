/**
 * M1.5 Phase 6: useRoomMembership — query hook.
 *
 * Calls `listRooms` on the gateway, then for every active (non-
 * disbanded) room it writes `setRoomMembership(roomId-as-session,
 * roomId)` into the room-membership store.
 *
 * Why the inverse mapping (sessionId → roomId AND roomId → roomId)?
 * The room-membership store keys by sessionId (the question the UI
 * asks is "is this session a room"). Phase 6 also makes the room
 * roster reachable from the chat mount: when the user opens a
 * session that IS a room, the chat panel populates with that
 * room's members. So we also write `room-{id}` as a session key →
 * the roomId. That second write is the seam a future Phase 7
 * "open the room in its own view" can pick up.
 *
 * The hook returns the React Query result so the caller can show
 * loading / error UI; consumers that only need the store effect
 * can call it without destructuring the result.
 *
 * Refresh cadence: 30s on the page is plenty for the chat mount.
 * A future Phase 7 can wire it to a WebSocket push from the
 * gateway (driver emits room.created / room.disbanded as
 * gateway.* events) for sub-second updates.
 */
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'

import { listRooms, type RoomInfo } from '@/api/hosted_rooms'
import { clearRoomMembership, setRoomMembership } from '@/store/room-membership'

const ROOMS_REFRESH_MS = 30_000

function applyRoomsToMembership(rooms: RoomInfo[]): void {
  // Strategy:
  //   - For every active (non-disbanded) room, write
  //     setRoomMembership(roomId, roomId) AND setRoomMembership(
  //     `room:${roomId}`, roomId). The first lets the chat mount
  //     see the room when the user opens a session whose id IS
  //     the room id. The second is the future "open the room in
  //     its own view" seam.
  //   - clearRoomMembership is intentionally NOT called here. A
  //     disband should clear the room's view (Phase 7), not
  //     a side effect of every list call. The list query is
  //     called often; clearing on each tick would race with the
  //     chat mount reading the store.
  for (const room of rooms) {
    if (room.disbanded_at) continue
    setRoomMembership(room.room_id, room.room_id)
    setRoomMembership(`room:${room.room_id}`, room.room_id)
  }
}

export function useRoomMembershipQuery() {
  const query = useQuery({
    queryKey: ['hosted_rooms', 'list'],
    queryFn: () => listRooms({ limit: 100 }),
    refetchInterval: ROOMS_REFRESH_MS,
    refetchOnWindowFocus: true,
    staleTime: 10_000
  })

  useEffect(() => {
    if (!query.data) return
    applyRoomsToMembership(query.data.rooms)
  }, [query.data])

  return query
}

/** Force a re-fetch of the room list (call from a button or after a
 *  user-driven create/disband to skip the 30s poll). */
export function _invalidateRoomMembershipQuery(queryClient: { invalidateQueries: (q: { queryKey: string[] }) => Promise<void> }): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: ['hosted_rooms', 'list'] })
}

// Silence the "unused" lint for clearRoomMembership (the future
// disband seam documented in this file's doc comment).
void clearRoomMembership
