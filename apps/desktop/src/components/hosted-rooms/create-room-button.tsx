/**
 * M1.5 Phase 7: create-room button + dialog.
 *
 * Renders a small "+ Room" button next to the chat title. Clicking
 * opens a dialog with two fields: name + members. Members are
 * seeded with the local user as a `user` member and a single
 * `agent` slot, so the user can name the room and either accept
 * the default agent roster or add more members. The dialog calls
 * the api/hosted_rooms.ts createRoom function and on success
 * invalidates the React Query so the new room shows up in the
 * membership store + the next useRoomMembershipQuery poll.
 *
 * Phase 7 scope: a single "+ Room" button in the chat shell. The
 * button is always visible (the room-membership gate in the
 * AgentProgressPanel still applies; the button is a *create* UI,
 * not a *join* UI). Phase 8+ can add a room picker that lists
 * existing rooms; today the user opens an existing room via the
 * slash command in zeloo_cli (see zeloo_cli/cli_commands_mixin.py
 * /room) and the chat mount picks it up via the 30s query poll.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { createRoom, type RoomMember, type RoomInfo } from '@/api/hosted_rooms'
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

export interface CreateRoomButtonProps {
  className?: string
}

export function CreateRoomButton({ className }: CreateRoomButtonProps) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className={className}
        onClick={() => setOpen(true)}
        data-testid="create-room-button"
      >
        + Room
      </Button>
      <CreateRoomDialog open={open} onOpenChange={setOpen} />
    </>
  )
}

interface CreateRoomDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

const DEFAULT_NAME = 'New Room'

function defaultMembers(): RoomMember[] {
  return [
    { member_id: 'user-boss', kind: 'user', display_name: 'You' },
    { member_id: 'agent-1', kind: 'agent', display_name: 'Agent 1', profile: 'default' }
  ]
}

export function CreateRoomDialog({ open, onOpenChange }: CreateRoomDialogProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [name, setName] = useState(DEFAULT_NAME)
  const [membersJson, setMembersJson] = useState(() => JSON.stringify(defaultMembers(), null, 2))
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (input: { name: string; members: RoomMember[] }) => createRoom(input),
    onSuccess: (room: RoomInfo) => {
      // Invalidate the room-list query so useRoomMembershipQuery
      // refetches and writes the new room into the membership store
      // immediately, without waiting for the 30s poll.
      void queryClient.invalidateQueries({ queryKey: ['hosted_rooms', 'list'] })
      void queryClient.setQueryData(['hosted_rooms', 'list'], (prev: unknown) => {
        const before = Array.isArray(prev) ? (prev as RoomInfo[]) : []
        return [...before, room]
      })
      onOpenChange(false)
      setName(DEFAULT_NAME)
      setMembersJson(JSON.stringify(defaultMembers(), null, 2))
      setError(null)
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : String(err))
    }
  })

  const submit = () => {
    setError(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(membersJson)
    } catch (e) {
      setError(`members JSON parse error: ${(e as Error).message}`)
      return
    }
    if (!Array.isArray(parsed) || parsed.length === 0) {
      setError('members must be a non-empty array')
      return
    }
    mutation.mutate({ name, members: parsed as RoomMember[] })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="create-room-dialog">
        <DialogHeader>
          <DialogTitle>Create hosted room</DialogTitle>
          <DialogDescription>
            A hosted room runs multiple agents in a single group
            chat. The members list is the roster of agents and the
            single user that owns the room.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2">
          <label className="grid gap-1 text-sm">
            <span>Name</span>
            <input
              data-testid="create-room-name"
              className="rounded border border-(--ui-border) bg-(--ui-background) px-2 py-1 text-sm"
              value={name}
              onChange={e => setName(e.target.value)}
              autoFocus
            />
          </label>
          <label className="grid gap-1 text-sm">
            <span>Members (JSON array of {`{member_id, kind, display_name?}`})</span>
            <textarea
              data-testid="create-room-members"
              className="rounded border border-(--ui-border) bg-(--ui-background) px-2 py-1 font-mono text-xs"
              rows={8}
              value={membersJson}
              onChange={e => setMembersJson(e.target.value)}
            />
          </label>
          {error && (
            <p data-testid="create-room-error" className="text-xs text-(--ui-destructive)">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
            {t.desktop.cancel}
          </Button>
          <Button
            data-testid="create-room-submit"
            onClick={submit}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? 'Creating…' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
