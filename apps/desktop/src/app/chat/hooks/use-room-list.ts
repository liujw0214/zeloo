/**
 * M1.5 Phase 8: useRoomList — fetch the full room list.
 *
 * Thin React Query wrapper around listRooms(). Used by RoomListDialog
 * to render the "Rooms" modal. Distinct from useRoomMembershipQuery,
 * which writes per-room entries into the membership store for the chat
 * mount; this hook returns the row data for display in a chooser UI.
 *
 * Refetch cadence: 30s on a soft stale time of 10s, with a manual
 * ``refetch()`` exposed for an explicit Refresh button.
 */
import { useQuery } from '@tanstack/react-query'

import { listRooms, type ListRoomsResponse, type RoomInfo } from '@/api/hosted_rooms'

const ROOMS_LIST_REFRESH_MS = 30_000

export function useRoomList() {
  return useQuery({
    queryKey: ['hosted_rooms', 'list', 'full'],
    queryFn: () => listRooms({ limit: 100 }),
    refetchInterval: ROOMS_LIST_REFRESH_MS,
    refetchOnWindowFocus: true,
    staleTime: 10_000
  })
}

/**
 * Format a unix epoch as a short, locale-neutral "YYYY-MM-DD HH:MM"
 * string. Lives in this module so the chooser doesn't pull a
 * heavyweight date library and the test can pin the exact format.
 */
export function formatRoomTimestamp(epoch: number): string {
  if (!epoch) return '—'
  const d = new Date(epoch * 1000)
  const yyyy = d.getUTCFullYear()
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(d.getUTCDate()).padStart(2, '0')
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mi = String(d.getUTCMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`
}

/** Count the user members in a room (the rest are agents / system). */
export function userMemberCount(room: RoomInfo): number {
  return room.members.filter(m => m.kind === 'user').length
}

/** Count the agent members in a room. */
export function agentMemberCount(room: RoomInfo): number {
  return room.members.filter(m => m.kind === 'agent' || m.kind === 'sub-agent').length
}

/** Re-exported for the dialog so it can share the response type. */
export type { ListRoomsResponse, RoomInfo }
