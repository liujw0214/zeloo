/**
 * M1.5 Phase 2: agent progress store.
 *
 * Holds the rolling tail of agent.* progress events for the active session
 * so a React component can render an activity stream. Modeled after
 * `subagent-snapshot.ts` (M1.4 in the TUI uses turnController.pushActivity;
 * here we keep a finite buffer so memory does not grow unbounded for
 * long sessions).
 *
 * M1.5 wiring:
 *   - gateway-event/agent-progress.ts → calls onAgentProgress(event, description)
 *   - use-message-stream (the gateway-event dispatcher) → onAgentProgress pushes
 *     into $agentProgressEvents here
 *   - any React component reads $agentProgressEvents and renders the list
 *
 * The store is keyed by session id; events for a different session do not
 * pollute the active session's view.
 */
import { atom, map } from 'nanostores'

import type { RpcEvent } from '@/types/Zeloo'

/** Per-event kind we render. Mirrors gateway/hosted_room_driver.py M1.2-M1.3. */
export type AgentProgressKind =
  | 'agent.thinking'
  | 'agent.done'
  | 'agent.failed'
  | 'agent.tool_call'
  | 'agent.tool_result'
  | 'agent.waiting_child'

const SUPPORTED_KINDS: ReadonlySet<AgentProgressKind> = new Set<AgentProgressKind>([
  'agent.thinking',
  'agent.done',
  'agent.failed',
  'agent.tool_call',
  'agent.tool_result',
  'agent.waiting_child',
])

export interface AgentProgressEntry {
  /** Stable per-event id (event_id or generated). */
  id: string
  sessionId: string
  kind: AgentProgressKind
  description: string
  /** When the entry was ingested locally (ms since epoch). */
  at: number
  /** Whether this is a terminal state (done or failed) — drives styling. */
  terminal: 'success' | 'failure' | null
}

/** Per-session ring buffer (newest at index 0, oldest at end). */
export const $agentProgressEvents = map<Record<string, AgentProgressEntry[]>>({})

/** How many entries to retain per session. Matches TUI M1.4's transient trail. */
const RETAIN_PER_SESSION = 32

/** Stable id derivation: payload.event_id if present, else kind+ts. */
function entryId(event: RpcEvent): string {
  const payload = (event.payload ?? {}) as { event_id?: string; timestamp?: number }
  if (typeof payload.event_id === 'string' && payload.event_id.length > 0) {
    return payload.event_id
  }
  const ts = typeof payload.timestamp === 'number' ? payload.timestamp : Date.now() / 1000
  return `${event.type}:${ts}`
}

function terminalFor(kind: AgentProgressKind): 'success' | 'failure' | null {
  if (kind === 'agent.done') return 'success'
  if (kind === 'agent.failed') return 'failure'
  return null
}

/**
 * Push a single event into the active session's ring buffer.
 * Returns the entry that was stored (useful for tests).
 */
export function pushAgentProgress(
  event: RpcEvent,
  description: string,
  sessionId: string,
): AgentProgressEntry | null {
  if (!SUPPORTED_KINDS.has(event.type as AgentProgressKind)) return null
  if (!sessionId) return null
  const entry: AgentProgressEntry = {
    id: entryId(event),
    sessionId,
    kind: event.type as AgentProgressKind,
    description,
    at: Date.now(),
    terminal: terminalFor(event.type as AgentProgressKind),
  }
  const all = $agentProgressEvents.get()
  const existing = all[sessionId] ?? []
  // Dedupe by id (gateway may re-emit the same event after reconnect)
  if (existing.some((e) => e.id === entry.id)) return entry
  const next = [entry, ...existing].slice(0, RETAIN_PER_SESSION)
  $agentProgressEvents.setKey(sessionId, next)
  return entry
}

/** Clear the buffer for a single session. Call on session switch / close. */
export function clearAgentProgress(sessionId: string): void {
  if (!sessionId) return
  const all = $agentProgressEvents.get()
  if (!(sessionId in all)) return
  // map.setKey with undefined removes the key
  $agentProgressEvents.setKey(sessionId, undefined)
}

/** Currently selected session for the activity panel. */
export const $agentProgressActiveSession = atom<string | null>(null)
