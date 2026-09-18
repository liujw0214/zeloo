/**
 * Tiny pub/sub for the @mention → group chat preset handoff.
 *
 * When the user types `@coder @researcher ...` in the Single-tab composer and
 * presses Send, ChatFallbackPanel publishes a GroupChatPreset; the parent
 * ChatFallbackTabbedPanel flips the mode to "group" and forwards the preset
 * to GroupChatPanel which consumes it once on mount and clears the slot.
 *
 * Kept module-level (no context / zustand) so the change stays inside the
 * chat page subtree — no impact on the rest of the dashboard.
 */
import { useEffect, useState } from "react";

export interface GroupChatPreset {
  /** Pre-fill the prompt textarea with this text (mentions already stripped). */
  prompt: string;
  /** Pre-select this profile as the host. */
  host: string;
  /** Pre-check these profiles as workers. */
  workers: string[];
}

type Listener = (preset: GroupChatPreset | null) => void;

let current: GroupChatPreset | null = null;
const listeners = new Set<Listener>();

export function publishGroupChatPreset(preset: GroupChatPreset): void {
  current = preset;
  for (const l of listeners) l(preset);
}

export function clearGroupChatPreset(): void {
  current = null;
  for (const l of listeners) l(null);
}

/**
 * React hook for the Group panel: returns the next preset exactly once, then
 * clears it so it doesn't re-fire on remount.
 *
 * Important: we DO NOT clear inside this hook on mount. When the Single tab
 * publishes a preset while GroupChatPanel is unmounted, `current` already holds
 * the value. On the next mount, useState reads `current` and we expose it.
 * Only after the consumer marks it consumed (via markPresetConsumed) does the
 * slot actually clear — see the hook return tuple below.
 */
export function useGroupChatPreset(): [GroupChatPreset | null, () => void] {
  const [preset, setPreset] = useState<GroupChatPreset | null>(current);
  useEffect(() => {
    const l: Listener = (p) => setPreset(p);
    listeners.add(l);
    // On subscription, also catch any value that arrived between render and effect.
    if (current !== preset) setPreset(current);
    return () => { listeners.delete(l); };
  }, []);
  const consume = (): void => {
    if (preset !== null) {
      current = null;
      setPreset(null);
    }
  };
  return [preset, consume];
}