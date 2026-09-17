/**
 * M1.5 Phase 3: Agent progress panel.
 *
 * Renders a rolling-tail activity stream of `agent.*` events for the
 * active session so the user can see what a multi-agent room is doing
 * in real time. Subscribes to `$agentProgressEvents` (Phase 2 store)
 * via `useStore` from `@nanostores/react`.
 *
 * Design notes:
 *   - The panel is a presentational component. The session it renders
 *     is determined by `$agentProgressActiveSession` (set by whoever
 *     mounted it). It is not coupled to AssistantUI / the chat surface;
 *     the host decides where to place it (slide-in panel, side rail,
 *     pinned above the composer, etc.).
 *   - `aria-live="polite"` so screen readers announce progress
 *     changes without interrupting the user mid-utterance. `aria-atomic`
 *     is per-entry so a new entry does not re-read the whole list.
 *   - Terminal states (`agent.done` / `agent.failed`) get distinct
 *     colors so a failed run is immediately visible.
 *   - The component is intentionally not memoised. The store pushes
 *     at most a handful of updates per second during a run; the render
 *     cost is dominated by the React tree, not by the subscription.
 *
 * Phase 3 scope: this file ships the component and its test. Mounting
 * it in the chat surface is a follow-up that needs product sign-off
 * (where on the screen does the panel live, does it stay visible
 * between turns, does the user collapse it).
 */
import { useStore } from '@nanostores/react'

import { $agentProgressEvents, type AgentProgressEntry } from '@/store/agent-progress'

const KIND_LABEL: Record<AgentProgressEntry['kind'], string> = {
  'agent.thinking': 'thinking',
  'agent.done': 'done',
  'agent.failed': 'failed',
  'agent.tool': 'tool',
  'agent.progress': 'progress',
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
}

export function AgentProgressPanel({ maxRows, className, hideWhenEmpty }: AgentProgressPanelProps) {
  const all = useStore($agentProgressEvents)
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

  return (
    <ul
      aria-live="polite"
      aria-relevant="additions"
      data-testid="agent-progress-panel"
      className={className}
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
}
