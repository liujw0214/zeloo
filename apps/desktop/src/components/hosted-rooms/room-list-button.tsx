/**
 * M1.5 Phase 8: RoomListButton + RoomListDialog.
 *
 * A second button next to "+ Room" in the chat shell. Clicking it
 * opens a chooser dialog that lists every active hosted room with
 * a one-line summary (name, member counts, last update). The user
 * can copy a room id, refresh the list, and see the count of
 * agents / users in each room.
 *
 * Per desktop AGENTS.md ("Offer; don't hijack"), the dialog does
 * NOT navigate the user into a room. To "open" a room today, the
 * user runs the zeloo_cli /room show <id> slash command, or
 * selects a session whose id equals the room id (the chat mount
 * auto-detects via the room-membership gate, Phase 4). Phase 9+
 * will add a per-room "open in this window" affordance once
 * product signs off on the layout.
 */
import { useState } from 'react'

import {
  agentMemberCount,
  formatRoomTimestamp,
  useRoomList,
  userMemberCount
} from '@/app/chat/hooks/use-room-list'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { useI18n } from '@/i18n'

export interface RoomListButtonProps {
  className?: string
}

export function RoomListButton({ className }: RoomListButtonProps) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className={className}
        onClick={() => setOpen(true)}
        data-testid="room-list-button"
      >
        Rooms
      </Button>
      <RoomListDialog open={open} onOpenChange={setOpen} />
    </>
  )
}

export interface RoomListDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function RoomListDialog({ open, onOpenChange }: RoomListDialogProps) {
  const { t } = useI18n()
  const query = useRoomList()
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const onCopy = async (roomId: string) => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(roomId)
        setCopiedId(roomId)
        // Clear the "Copied" hint after 1.5s so the user can copy again.
        setTimeout(() => setCopiedId(prev => (prev === roomId ? null : prev)), 1500)
      }
    } catch {
      // Clipboard may be unavailable in some test environments; ignore.
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="room-list-dialog"
        className="max-w-2xl"
      >
        <DialogHeader>
          <DialogTitle>Hosted rooms</DialogTitle>
          <DialogDescription>
            Every active group chat hosted by this gateway. Click
            a row to copy the room id; the zeloo_cli <code>/room show
            &lt;id&gt;</code> command prints the full member list.
          </DialogDescription>
        </DialogHeader>
        <div data-testid="room-list-body" className="max-h-[60vh] overflow-y-auto">
          {query.isLoading && <p className="py-6 text-center text-sm text-(--ui-text-muted)">Loading…</p>}
          {query.isError && (
            <p
              data-testid="room-list-error"
              className="py-6 text-center text-sm text-(--ui-destructive)"
            >
              Failed to load rooms: {(query.error as Error).message}
            </p>
          )}
          {query.data && query.data.rooms.length === 0 && (
            <p
              data-testid="room-list-empty"
              className="py-6 text-center text-sm text-(--ui-text-muted)"
            >
              No active rooms. Use the + Room button to create one.
            </p>
          )}
          {query.data && query.data.rooms.length > 0 && (
            <ul className="divide-y divide-(--ui-border)">
              {query.data.rooms.map(room => (
                <li
                  key={room.room_id}
                  data-testid="room-list-row"
                  data-room-id={room.room_id}
                  className="flex items-center justify-between gap-3 px-2 py-2 hover:bg-(--ui-muted)/40"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{room.name}</p>
                    <p className="truncate font-mono text-xs text-(--ui-text-muted)">
                      {room.room_id}
                    </p>
                    <p className="text-xs text-(--ui-text-muted)">
                      {userMemberCount(room)} user · {agentMemberCount(room)} agent
                      {' · '}
                      updated {formatRoomTimestamp(room.updated_at)}
                    </p>
                  </div>
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() => void onCopy(room.room_id)}
                    data-testid="room-list-copy"
                    data-room-id={room.room_id}
                  >
                    {copiedId === room.room_id ? 'Copied' : 'Copy id'}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
            data-testid="room-list-refresh"
          >
            {query.isFetching ? 'Refreshing…' : 'Refresh'}
          </Button>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t.desktop.cancel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
