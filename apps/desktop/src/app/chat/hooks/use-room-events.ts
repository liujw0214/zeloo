/**
 * M1.5 Phase 9 part 2: useRoomEvents — fetch the per-room event log.
 *
 * React Query wrapper around listRoomEvents(). Refetch cadence
 * matches the room list (30s) so a fresh agent.* event surfaces
 * within at most 30s; a manual refetch() is exposed for the dialog
 * "Refresh" button.
 */
import { useQuery } from '@tanstack/react-query'

import {
  listRoomEvents,
  type ListRoomEventsResponse,
  type RoomEvent
} from '@/api/hosted_rooms'

const ROOM_EVENTS_REFRESH_MS = 30_000

export function useRoomEvents(
  roomId: string | null,
  options: { limit?: number; kinds?: string[] } = {}
) {
  return useQuery({
    queryKey: ['hosted_rooms', 'events', roomId, options],
    queryFn: () => listRoomEvents(roomId as string, { limit: options.limit ?? 100, kinds: options.kinds }),
    refetchInterval: ROOM_EVENTS_REFRESH_MS,
    refetchOnWindowFocus: true,
    staleTime: 10_000,
    enabled: roomId !== null
  })
}

export type { ListRoomEventsResponse, RoomEvent }

/** Group a flat list of events by kind for compact rendering. */
export function groupEventsByKind(events: RoomEvent[]): Map<string, RoomEvent[]> {
  const groups = new Map<string, RoomEvent[]>()
  for (const ev of events) {
    const bucket = groups.get(ev.kind) ?? []
    bucket.push(ev)
    groups.set(ev.kind, bucket)
  }
  return groups
}

/** Format a unix epoch (seconds) as a short HH:MM:SS string. */
export function formatEventTime(epoch: number): string {
  if (!epoch) return '—'
  const d = new Date(epoch * 1000)
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  const ss = String(d.getUTCSeconds()).padStart(2, '0')
  return `${hh}:${mm}:${ss}`
}
