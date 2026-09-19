/**
 * GroupChatPanel — multi-agent chat composer for the dashboard /chat tab.
 *
 * Always-visible HTTP composer that:
 *  1. Loads the profile list via api.getProfiles() and lets the user pick
 *     a host + 1..N workers (checkboxes).
 *  2. POSTs {prompt, host, workers[]} to /api/group-chat/send which fans
 *     out to worker profiles in parallel, then asks the host to integrate
 *     the worker outputs into a single reply.
 *  3. Renders the host reply + per-worker trail in a column layout.
 *
 * Works without the PTY / TUI stack (no xterm.js, no node TUI), so it is a
 * reliable fallback alongside ChatFallbackPanel. Both panels share the
 * /chat tab surface — Single mode uses ChatFallbackPanel (one-shot HTTP),
 * Group mode uses this component (multi-agent HTTP).
 */
import * as React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type {
  GroupChatSendResponse,
  GroupChatStatusResponse,
  GroupChatWorkerResult,
  ProfileInfo,
} from "@/lib/api";
import { cn } from "@/lib/utils";
/**
 * Inline @profile preview for the GroupChatPanel prompt textarea.
 *
 * `agent` is intentionally not threaded in: by the time a prompt arrives
 * here, the upstream caller has already resolved `@agent(...)` into a
 * concrete (host, workers) tuple via the GroupChatPreset, so showing an
 * `@agent` chip again would be confusing.
 */
function GroupPromptPreview({
  prompt,
  profiles,
}: {
  prompt: string;
  profiles: ProfileInfo[];
}): React.JSX.Element | null {
  const knownNames = React.useMemo(
    () => profiles.map((p) => p.name),
    [profiles],
  );
  const mentions = React.useMemo(
    () => parseProfileMentions(prompt, knownNames),
    [prompt, knownNames],
  );
  return (
    <MentionPreview
      valid={mentions.valid}
      unknown={mentions.unknown}
      className="px-0 mt-1"
    />
  );
}

import { MentionPreview } from "@/components/MentionPreview";
import { parseProfileMentions } from "@/lib/profileMentions";
import type { GroupChatPreset } from "@/lib/groupChatPreset";

interface Round {
  id: string;
  prompt: string;
  response: GroupChatSendResponse | null;
  error: string | null;
  ts: number;
}

function defaultProfileName(profiles: ProfileInfo[]): string {
  const def = profiles.find((p) => p.is_default);
  return def?.name ?? profiles[0]?.name ?? "";
}

function newRoundId(): string {
  return `r_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

export function GroupChatPanel({
  initialPreset = null,
  onConsumed,
}: {
  initialPreset?: GroupChatPreset | null;
  /** Called exactly once after a preset has been applied to component state. */
  onConsumed?: () => void;
} = {}): React.JSX.Element {
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const [status, setStatus] = useState<GroupChatStatusResponse | null>(null);
  const [host, setHost] = useState<string>("");
  const [workers, setWorkers] = useState<Set<string>>(new Set());
  const [prompt, setPrompt] = useState("");

  // The panel already has `profiles: ProfileInfo[]` loaded by the existing
  // useEffect above — we reuse it directly for the @profile live preview
  // under the prompt textarea. By the time a prompt arrives here, the
  // upstream caller (ChatPage / CronPage / WebhooksPage) has already
  // resolved `@agent(...)` into a concrete (host, workers) tuple via the
  // GroupChatPreset, so we deliberately skip the @agent chip here.
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [collapsed, setCollapsed] = useState(false);

  // Load profiles + status on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [{ profiles: list }, st] = await Promise.all([
          api.getProfiles(),
          api.getGroupChatStatus().catch(() => null),
        ]);
        if (cancelled) return;
        setProfiles(list);
        setStatus(st);
        const def = defaultProfileName(list);
        if (def) setHost(def);
      } catch (e: unknown) {
        if (!cancelled) setError(`Failed to load profiles: ${String(e)}`);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Apply the @mention preset exactly once. Profiles are loaded async above,
  // so we defer the apply until both `profiles` and `initialPreset` are
  // ready; if the user landed here without a preset, this no-ops.
  const [presetApplied, setPresetApplied] = React.useState(false);
  React.useEffect(() => {
    if (presetApplied) return;
    if (!initialPreset) return;
    if (profiles.length === 0) return;
    // If the mentioned host no longer exists, fall back to whatever the
    // dashboard considers default rather than silently dropping the preset.
    const hostProfile =
      profiles.find((p) => p.name === initialPreset.host) ??
      profiles.find((p) => p.is_default) ??
      profiles[0];
    if (!hostProfile) return;
    const effectiveHost = hostProfile.name;
    setHost(effectiveHost);
    setWorkers(
      new Set(
        initialPreset.workers.filter(
          (w) =>
            profiles.some((p) => p.name === w) && w !== effectiveHost,
        ),
      ),
    );
    setPrompt(initialPreset.prompt);
    setCollapsed(false); // expand so user sees the prefilled state
    setPresetApplied(true);
    onConsumed?.();
  }, [initialPreset, profiles, presetApplied, onConsumed]);

  const maxWorkers = status?.max_workers ?? 8;
  const hostProfile = profiles.find((p) => p.name === host);

  // Reset workers if a non-existent profile is set (defensive — should not happen).
  useEffect(() => {
    setWorkers((prev) => {
      const next = new Set<string>();
      for (const w of prev) if (profiles.some((p) => p.name === w) && w !== host) next.add(w);
      return next;
    });
  }, [profiles, host]);

  const toggleWorker = useCallback((name: string) => {
    setWorkers((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else if (next.size < maxWorkers) next.add(name);
      return next;
    });
  }, [maxWorkers]);

  const canSend = useMemo(() => {
    return !busy
      && prompt.trim().length > 0
      && host.length > 0
      && workers.size >= 1
      && !workers.has(host);
  }, [busy, prompt, host, workers]);

  async function send(): Promise<void> {
    const text = prompt.trim();
    if (!canSend) return;
    setBusy(true);
    setError(null);
    const round: Round = {
      id: newRoundId(),
      prompt: text,
      response: null,
      error: null,
      ts: Date.now(),
    };
    setRounds((rs) => [...rs, round]);
    try {
      const resp = await api.sendGroupChat({
        prompt: text,
        host,
        workers: Array.from(workers),
        timeout_s: 180,
      });
      setRounds((rs) => rs.map((r) => (r.id === round.id ? { ...r, response: resp } : r)));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setRounds((rs) => rs.map((r) => (r.id === round.id ? { ...r, error: msg } : r)));
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  const workerOptions = profiles.filter((p) => p.name !== host);

  return (
    <div
      className={cn(
        "mx-4 mb-4 rounded-xl border border-current/10",
        "bg-card/30 backdrop-blur-sm",
        "shadow-sm shadow-midground/5",
      )}
      data-testid="group-chat-panel"
    >
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
        className={cn(
          "flex w-full items-center justify-between gap-3",
          "px-4 py-3 text-left",
          "font-mondwest text-sm tracking-[0.08em] text-text-secondary",
          "hover:bg-card/40 transition-colors rounded-t-xl",
        )}
      >
        <span className="flex items-center gap-2">
          <span aria-hidden className="text-base leading-none">💬</span>
          <span className="font-medium">Group chat</span>
          <span className="text-text-tertiary">
            · host + {workers.size} worker{workers.size === 1 ? "" : "s"}
          </span>
        </span>
        <span aria-hidden className="text-xs text-text-tertiary">
          {collapsed ? "▾ expand" : "▴ collapse"}
        </span>
      </button>

      {!collapsed && (
        <div className="border-t border-current/10 p-4 space-y-3">
          {status && !status.available && (
            <div className="rounded-md border border-amber-300/40 bg-amber-50/40 px-3 py-2 text-xs text-amber-900">
              Group chat backend unavailable (Zeloo CLI not found at {status.cli_path ?? "?"}).
              Single chat still works.
            </div>
          )}

          {/* Host selector */}
          <div>
            <label className="block text-xs font-medium text-text-tertiary mb-1">
              Host (synthesizes the final reply)
            </label>
            <select
              value={host}
              onChange={(e) => setHost(e.target.value)}
              className={cn(
                "w-full rounded-md border border-current/15 bg-background/40",
                "px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-current/30",
              )}
            >
              {profiles.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}{p.is_default ? " (default)" : ""}
                  {p.model ? ` · ${p.model}` : ""}
                </option>
              ))}
            </select>
            {hostProfile && (
              <p className="mt-1 text-[11px] text-text-tertiary">
                {hostProfile.skill_count} skills
                {hostProfile.description ? ` · ${hostProfile.description.slice(0, 80)}` : ""}
              </p>
            )}
          </div>

          {/* Workers multi-select */}
          <div>
            <label className="block text-xs font-medium text-text-tertiary mb-1">
              Workers ({workers.size}/{maxWorkers}, runs in parallel)
            </label>
            {workerOptions.length === 0 ? (
              <p className="text-xs text-text-tertiary">
                No other profiles available. Create more at{" "}
                <a href="/profiles" className="underline">/profiles</a>.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {workerOptions.map((p) => {
                  const checked = workers.has(p.name);
                  const disabled = !checked && workers.size >= maxWorkers;
                  return (
                    <label
                      key={p.name}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full px-3 py-1",
                        "border text-xs cursor-pointer transition-colors",
                        checked
                          ? "border-current/40 bg-current/10 text-text-primary"
                          : "border-current/15 bg-background/30 text-text-secondary",
                        disabled && "opacity-50 cursor-not-allowed",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => toggleWorker(p.name)}
                        className="size-3 accent-current"
                      />
                      <span>{p.name}</span>
                      {p.model && (
                        <span className="text-text-tertiary text-[10px]">· {p.model}</span>
                      )}
                    </label>
                  );
                })}
              </div>
            )}
          </div>

          {/* Prompt + send */}
          <div>
            <label className="block text-xs font-medium text-text-tertiary mb-1">
              Prompt
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  void send();
                }
              }}
              placeholder="Ask the group… (⌘/Ctrl+Enter to send)"
              rows={3}
              className={cn(
                "w-full rounded-md border border-current/15 bg-background/40",
                "px-3 py-2 text-sm resize-y focus:outline-none focus:ring-1 focus:ring-current/30",
              )}
            />
            <GroupPromptPreview prompt={prompt} profiles={profiles} />
            <div className="mt-2 flex items-center justify-between">
              <p className="text-[11px] text-text-tertiary">
                Fans out to {workers.size || 0} worker{workers.size === 1 ? "" : "s"} in
                parallel, then asks <span className="font-medium">{host || "—"}</span> to integrate.
              </p>
              <button
                type="button"
                onClick={() => void send()}
                disabled={!canSend}
                className={cn(
                  "rounded-md px-4 py-1.5 text-sm font-medium",
                  "transition-colors",
                  canSend
                    ? "bg-current/15 hover:bg-current/25 text-text-primary"
                    : "bg-current/5 text-text-tertiary cursor-not-allowed",
                )}
              >
                {busy ? "Sending…" : "Send to group"}
              </button>
            </div>
          </div>

          {error && (
            <div className="rounded-md border border-red-300/40 bg-red-50/40 px-3 py-2 text-xs text-red-900">
              {error}
            </div>
          )}

          {/* Round history */}
          {rounds.length > 0 && (
            <div className="space-y-3 pt-2">
              {rounds.slice().reverse().map((r) => (
                <RoundView key={r.id} round={r} hostName={host} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RoundView({ round, hostName }: { round: Round; hostName: string }): React.JSX.Element {
  if (round.error) {
    return (
      <div className="rounded-md border border-red-300/30 bg-red-50/30 p-3">
        <p className="text-[11px] text-text-tertiary mb-1">
          {new Date(round.ts).toLocaleTimeString()} · failed
        </p>
        <p className="text-xs font-medium mb-1">Prompt: {round.prompt.slice(0, 100)}</p>
        <p className="text-xs text-red-700 whitespace-pre-wrap">{round.error}</p>
      </div>
    );
  }
  const resp = round.response;
  if (!resp) {
    return (
      <div className="rounded-md border border-current/10 bg-background/30 p-3">
        <p className="text-[11px] text-text-tertiary mb-1">
          {new Date(round.ts).toLocaleTimeString()} · running…
        </p>
        <p className="text-xs">Prompt: {round.prompt.slice(0, 100)}</p>
      </div>
    );
  }
  return (
    <div className="rounded-md border border-current/10 bg-background/30 p-3 space-y-2">
      <div className="flex items-center justify-between text-[11px] text-text-tertiary">
        <span>{new Date(round.ts).toLocaleTimeString()}</span>
        <span>
          {resp.total_workers} worker{resp.total_workers === 1 ? "" : "s"} ·
          {" "}{resp.failed_workers} failed · {resp.elapsed_s}s
        </span>
      </div>
      <p className="text-xs font-medium text-text-primary">
        → {round.prompt.slice(0, 120)}{round.prompt.length > 120 ? "…" : ""}
      </p>

      {/* Host reply (the headline result) */}
      <div className="rounded-md bg-current/8 p-3 border border-current/15">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[11px] font-medium uppercase tracking-wider text-text-secondary">
            ★ {hostName} (host)
          </span>
          <span className="text-[11px] text-text-tertiary">{resp.host_elapsed_s}s</span>
        </div>
        <p className="text-sm whitespace-pre-wrap text-text-primary">
          {resp.host_output || "(empty)"}
        </p>
      </div>

      {/* Worker trail */}
      <details className="text-xs">
        <summary className="cursor-pointer text-text-tertiary hover:text-text-secondary">
          Worker trail ({resp.workers.length})
        </summary>
        <div className="mt-2 space-y-2">
          {resp.workers.map((w: GroupChatWorkerResult) => (
            <WorkerView key={w.name} w={w} />
          ))}
        </div>
      </details>
    </div>
  );
}

function WorkerView({ w }: { w: GroupChatWorkerResult }): React.JSX.Element {
  return (
    <div className={cn(
      "rounded-md border p-2",
      w.ok ? "border-current/10 bg-background/20" : "border-red-300/30 bg-red-50/20",
    )}>
      <div className="flex items-center justify-between text-[11px]">
        <span className="font-medium text-text-secondary">
          {w.ok ? "✓" : "✗"} {w.name}
        </span>
        <span className="text-text-tertiary">{w.elapsed_s}s</span>
      </div>
      <p className={cn(
        "mt-1 text-xs whitespace-pre-wrap",
        w.ok ? "text-text-secondary" : "text-red-700",
      )}>
        {w.ok ? (w.output || "(empty)") : (w.error ?? "unknown error")}
      </p>
    </div>
  );
}

export default GroupChatPanel;