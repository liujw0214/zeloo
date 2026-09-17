/**
 * M1.5: agent.* event handler for Desktop.
 *
 * Renders group-chat room progress events (agent.thinking, agent.done,
 * agent.failed, agent.tool, agent.progress, agent.waiting_child) emitted
 * by the room driver (gateway/hosted_room_driver.py, M1.2-M1.3) and
 * type-defined in TUI (ui-tui/src/gatewayTypes.ts: AgentProgressPayload,
 * M1.4).
 *
 * Per apps/desktop/src/AGENTS.md "Surface capability is a property of
 * the SESSION": this handler is a property of the session that owns the
 * room. It does not need ZELOO_DESKTOP=1 (that gate is for native
 * panes). It only fires when the gateway emits the event on a session
 * the desktop is currently viewing.
 *
 * Phase 2 wiring: the handler also pushes each accepted event into the
 * `$agentProgressEvents` ring buffer keyed by session id, so a React
 * component can render the activity stream without each component
 * re-walking the gateway event.
 */
import type { RpcEvent } from '@/types/Zeloo'

import { pushAgentProgress } from '@/store/agent-progress'

import type { GatewayEventContext, GatewayEventHandler } from './types'

/**
 * M1.5 agent.* progress events. Names mirror ui-tui/src/gatewayTypes.ts
 * (TUI M1.4) and gateway/hosted_room_driver.py (M1.2-M1.3 emitter).
 */
const AGENT_PROGRESS_EVENT_TYPES = new Set([
  'agent.thinking',
  'agent.done',
  'agent.failed',
  'agent.tool',
  'agent.progress',
  'agent.waiting_child',
] as const)

/** Human-readable label per event type — used for DevTools / future activity log. */
const AGENT_EVENT_LABEL: Record<string, string> = {
  'agent.thinking': 'thinking',
  'agent.done': 'done',
  'agent.failed': 'failed',
  'agent.tool': 'tool',
  'agent.progress': 'progress',
  'agent.waiting_child': 'waiting for child',
}

/** Minimal shape of the agent.* event payload. Mirrors the TUI contract. */
interface AgentProgressPayload {
  task_id?: string
  model?: string
  round?: number
  tool?: string
  call_id?: string
  duration_ms?: number
  status?: string
  child_target?: string
  child_task_id?: string
  text?: string
  terminal_kind?: 'success' | 'failure' | 'cancelled'
  error_class?: string
  error_message?: string
  tokens?: { input?: number; output?: number }
}

/** Returns true if the event is a M1 agent.* progress event. */
export function isAgentProgressEvent(event: RpcEvent): boolean {
  return AGENT_PROGRESS_EVENT_TYPES.has(event.type as never)
}

/** Build a short human description for an event payload. */
function describe(event: RpcEvent, payload: AgentProgressPayload): string {
  const label = AGENT_EVENT_LABEL[event.type] ?? event.type
  const parts: string[] = []
  if (payload.task_id) parts.push(`task=${payload.task_id}`)
  if (payload.round !== undefined) parts.push(`round=${payload.round}`)
  if (payload.model) parts.push(`model=${payload.model}`)
  if (payload.tool) parts.push(`tool=${payload.tool}`)
  if (payload.call_id) parts.push(`call_id=${payload.call_id}`)
  if (payload.duration_ms !== undefined) parts.push(`${payload.duration_ms}ms`)
  if (payload.status) parts.push(`status=${payload.status}`)
  if (payload.child_target) parts.push(`child=${payload.child_target}`)
  if (payload.terminal_kind) parts.push(`terminal=${payload.terminal_kind}`)
  if (payload.error_class) parts.push(`error=${payload.error_class}`)
  if (payload.text) parts.push(`text=${payload.text.slice(0, 80)}`)
  if (payload.tokens) {
    const t = payload.tokens
    parts.push(`tokens=${(t.input ?? 0) + (t.output ?? 0)}`)
  }
  const detail = parts.length > 0 ? ` (${parts.join(' ')})` : ''
  return `${label}${detail}`
}

/**
 * M1.5 handler: log agent.* events to console (DevTools), push to the
 * $agentProgressEvents ring buffer (Phase 2), and return true to
 * indicate the event was consumed.
 */
export function handleAgentProgressEvent(ctx: GatewayEventContext): boolean {
  const { event, sessionId } = ctx
  if (!AGENT_PROGRESS_EVENT_TYPES.has(event.type as never)) {
    return false  // not for us; let other handlers try
  }
  const payload = (event.payload ?? {}) as AgentProgressPayload
  const text = describe(event, payload)

  // Phase 1: console trail so events are visible in DevTools.
  if (typeof console !== 'undefined') {
    const fn = event.type === 'agent.failed' ? console.error : console.debug
    fn(`[M1.5 agent.progress] ${text}`)
  }

  // Phase 2: push into the per-session ring buffer. sessionId is resolved
  // by the dispatcher before any handler runs (see
  // resolveGatewayEventSessionId in dispatcher index.ts), so we can
  // key on it directly without an explicit dep.
  if (sessionId) {
    try {
      pushAgentProgress(event, text, sessionId)
    } catch (err) {
      if (typeof console !== 'undefined') {
        console.warn('[M1.5 agent.progress] pushAgentProgress threw:', err)
      }
    }
  }

  // Back-compat hook for any external consumer that wants the raw
  // description without going through the store.
  const onProgress = (ctx.deps as { onAgentProgress?: (e: RpcEvent, description: string) => void }).onAgentProgress
  if (typeof onProgress === 'function') {
    try {
      onProgress(event, text)
    } catch (err) {
      if (typeof console !== 'undefined') {
        console.warn('[M1.5 agent.progress] observer threw:', err)
      }
    }
  }

  return true
}
