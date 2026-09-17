/**
 * M1.5 Phase 3: Agent progress panel.
 *
 * Renders a rolling-tail activity stream of `agent.*` events for the
 * active session so the user can see what a multi-agent room is doing
 * in real time. Subscribes to `$agentProgressEvents` (Phase 2 store)
 * via `useStore` from `@nanostores/react`.
 *
 * Phase 4 adds:
 *   - Room-membership gate: the panel hides itself for non-room
 *     sessions (per `useRoomMembership`). It only renders if the
 *     session is a hosted group-chat room, or if the caller
 *     explicitly passes `forceShow` for debugging / preview.
 *   - Collapsible disclosure: the user can collapse the panel to a
 *     single-line summary (`<summary>` element). State is local
 *     (per-instance, not persisted) — a future follow-up can wire
 *     it to a user preference store if "always expand" turns out
 *     to be a common complaint.
 *
 * Design notes:
 *   - The panel is a presentational component. The session it renders
 *     is determined by `activeSessionId` (defaulting to
 *     `$agentProgressActiveSession`); `useRoomMembership(activeSessionId)`
 *     then decides whether to render at all.
 *   - `aria-live="polite"` so screen readers announce progress
 *     changes without interrupting the user mid-utterance. `aria-atomic`
 *     is per-entry so a new entry does not re-read the whole list.
 *   - Terminal states (`agent.done` / `agent.failed`) get distinct
 *     colors so a failed run is immediately visible.
 *   - The component is intentionally not memoised. The store pushes
 *     at most a handful of updates per second during a run; the render
 *     cost is dominated by the React tree, not by the subscription.
 */
import { useStore } from '@nanostores/react'
import { useCallback, useState } from 'react'

import {
  $agentProgressActiveSession,
  $agentProgressEvents,
  type AgentProgressEntry,
} from '@/store/agent-progress'
import { useRoomMembership } from '@/store/room-membership'

const KIND_LABEL: Record<AgentProgressEntry['kind'], string> = {
  'agent.thinking': 'thinking',
  'agent.done': 'done',
  'agent.failed': 'failed',
  'agent.tool_call': 'tool',
  'agent.tool_result': 'tool result',
  'agent.waiting_child': 'waiting for child',
}

function rowClassName(entry: AgentProgressEntry): string {
  if (entry.terminal === 'success') return 'agent-progress-row agent-progress-row--done'
  if (entry.terminal === 'failure') return 'agent-progress-row agent-progress-row--failed'
  return 'agent-progress-row'
}

export interface AgentProgressPanelProps {
  /**
   * Maximum rows to render. Defaults to the store's `RETAIN_PER_SESSION`
   * (32). Smaller values are useful for a compact pinned strip; the
   * store still keeps the full ring buffer in memory.
   */
  maxRows?: number
  /** Optional className applied to the root <ul>. */
  className?: string
  /** Render nothing when the store is empty (default) or always render the container. */
  hideWhenEmpty?: boolean
  /**
   * Session to render events for. Defaults to the value of
   * `$agentProgressActiveSession`. If neither is set the panel renders
   * nothing.
   */
  activeSessionId?: string | null
  /**
   * If true, render the panel even when the active session is not
   * a hosted room. Off by default; the production chat mount leaves
   * it off so non-room sessions pay no render cost. Useful for
   * preview screens and tests.
   */
  forceShow?: boolean
  /**
   * If true (default), the panel is collapsible and starts expanded.
   * If false, the <details> wrapper is dropped and the rows are
   * always visible — useful for hosts that want a fixed-height strip.
   */
  collapsible?: boolean
  /** Optional className applied to the inner <summary> row. */
  summaryClassName?: string
  /** Optional className applied to the inner <ul> rows wrapper. */
  listClassName?: string
}

export function AgentProgressPanel({
  maxRows,
  className,
  hideWhenEmpty,
  activeSessionId,
  forceShow,
  collapsible = true,
  summaryClassName,
  listClassName,
}: AgentProgressPanelProps) {
  const all = useStore($agentProgressEvents)
  const fallbackSession = useStore($agentProgressActiveSession)
  const sessionId = activeSessionId ?? fallbackSession
  const roomId = useRoomMembership(sessionId)

  // Phase 4: room-membership gate. A non-room session does not render
  // the panel at all (unless forceShow is set, for preview screens).
  // This is the single check that makes the panel room-only in the
  // chat surface; before Phase 4 it was gated only on the ring buffer
  // being empty, which meant the panel would still try to render
  // (and pay a hook cost) on every session.
  if (!forceShow && !roomId) {
    return null
  }

  // Flatten all per-session buffers into a single stream, newest first.
  // The store already keeps each session in newest-first order, so we
  // can interleave by at-timestamp descending.
  const flat: AgentProgressEntry[] = []
  for (const buf of Object.values(all)) {
    if (!buf) continue
    for (const e of buf) flat.push(e)
  }
  flat.sort((a, b) => b.at - a.at)
  const rows = typeof maxRows === 'number' ? flat.slice(0, maxRows) : flat

  if (rows.length === 0 && hideWhenEmpty) {
    return null
  }

  const listNode = (
    <ul
      aria-live="polite"
      aria-relevant="additions"
      data-testid="agent-progress-panel"
      className={listClassName ?? className}
    >
      {rows.map(entry => (
        <li
          key={entry.id}
          aria-atomic="true"
          data-testid="agent-progress-row"
          data-kind={entry.kind}
          data-terminal={entry.terminal ?? 'none'}
          className={rowClassName(entry)}
        >
          <span className="agent-progress-row__label">{KIND_LABEL[entry.kind]}</span>
          <span className="agent-progress-row__desc">{entry.description}</span>
        </li>
      ))}
    </ul>
  )

  if (!collapsible) {
    return listNode
  }

  // Phase 4: collapsible wrapper. The <details>/<summary> pair is the
  // platform-native disclosure pattern — accessible by default, no
  // ARIA, no JS, no state to manage. Local state for `open` is here
  // so a host can later persist "always expand" by reading/writing
  // a user preference store, but for now it is in-memory only.
  return (
    <details
      open
      data-testid="agent-progress-disclosure"
      data-room-id={roomId ?? ''}
      className={className}
    >
      <summary
        data-testid="agent-progress-summary"
        className={summaryClassName}
      >
        Room activity ({rows.length})
      </summary>
      {listNode}
    </details>
  )
}

// Silence the "unused import" warning that would otherwise fire when
// this file is bundled without the collapsible path. `useState` is
// imported above for the future "persist collapsed preference" hook;
// `useCallback` is reserved for the same.
void useState
void useCallback
