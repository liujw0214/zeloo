import * as React from "react";
import { Users } from "lucide-react";
import { cn } from "@/lib/utils";

export interface MentionPreviewAgent {
  /** Whether `@agent` was detected in the prompt. */
  present: boolean;
  /** Whether the inline options (host/workers) have valid profile-name syntax. */
  optionsValid: boolean;
  /** Explicit host from `host=<profile>`; undefined when bare / workers-only. */
  host?: string;
  /** Explicit workers from `workers=a,b,c`; undefined when bare / host-only. */
  workers?: string[];
}

interface MentionPreviewProps {
  /** Valid mentions — profile names that exist and will be dispatched. */
  valid: string[];
  /** Unknown mentions — rendered as a warning so the user can correct typos. */
  unknown: string[];
  /** Extra hint shown to the right of the chip strip when fan-out will fire. */
  className?: string;
  /**
   * `@agent` meta-mention state. When `present`, an extra star chip is shown
   * indicating fan-out will fire via the `@agent` path (overrides any plain
   * @profile host/workers selection — the backend resolves @agent first).
   */
  agent?: MentionPreviewAgent;
}

/**
 * Inline chip strip rendered under the Single-tab textarea while the user is
 * typing. Shows recognized profile mentions as filled chips and typos / unknown
 * profiles as outlined chips so the user can self-correct before sending.
 *
 * Visual cue:
 *   0 mentions       → nothing rendered (stay out of the way)
 *   1 valid mention  → "Will route to @x" — single agent (no fan-out)
 *   ≥2 valid mentions → "Will fan out: host=first, workers=rest"
 *
 * Designed to read as part of the prompt surface, not a popup.
 */
export function MentionPreview({
  valid,
  unknown,
  className,
  agent,
}: MentionPreviewProps): React.JSX.Element | null {
  const hasAgent = !!agent?.present;
  const hasProfileChips = valid.length > 0 || unknown.length > 0;
  if (!hasAgent && !hasProfileChips) return null;

  const willFanOut = valid.length >= 2 || hasAgent;
  // host = valid[0];  // referenced implicitly via `valid[0]` below
  const workers = valid.slice(1);

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1.5 px-1 text-[11px]",
        "tracking-wide text-text-tertiary",
        className,
      )}
      aria-live="polite"
    >
      {hasAgent && (
        <>
          <span
            className="rounded bg-current/15 px-1.5 py-0.5 font-mono text-text-primary"
            title={
              agent && !agent.optionsValid
                ? "@agent options have invalid profile names"
                : "Multi-agent fan-out via @agent"
            }
          >
            ★ @agent
          </span>
          {agent?.host && (
            <span className="rounded bg-current/8 px-1.5 py-0.5 font-mono text-text-secondary">
              host=@{agent.host}
            </span>
          )}
          {agent?.workers && agent.workers.length > 0 && (
            <>
              <span className="opacity-60">·</span>
              <span className="rounded bg-current/8 px-1.5 py-0.5 font-mono text-text-secondary">
                {agent.workers.length} worker{agent.workers.length === 1 ? "" : "s"}
              </span>
            </>
          )}
          {agent && !agent.optionsValid && (
            <span
              className="rounded border border-current/20 px-1.5 py-0.5 font-mono text-text-tertiary line-through opacity-70"
              title="Invalid profile name(s) in @agent options"
            >
              bad option
            </span>
          )}
          {hasProfileChips && <span className="opacity-40">·</span>}
        </>
      )}

      {valid.length >= 1 && (
        <>
          <Users className="h-3 w-3 shrink-0 opacity-70" />
          <span>
            {willFanOut
              ? `Will fan out · host `
              : `Will route to `}
          </span>
          {valid.map((name, i) => (
            <React.Fragment key={name}>
              {i > 0 && <span className="opacity-60">·</span>}
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 font-mono",
                  i === 0 && willFanOut
                    ? "bg-current/15 text-text-primary"
                    : "bg-current/8 text-text-secondary",
                )}
              >
                @{name}
              </span>
            </React.Fragment>
          ))}
          {willFanOut && workers.length > 0 && (
            <span className="opacity-60">
              ({workers.length} worker{workers.length === 1 ? "" : "s"})
            </span>
          )}
        </>
      )}

      {unknown.map((name) => (
        <span
          key={name}
          className="rounded border border-current/20 px-1.5 py-0.5 font-mono text-text-tertiary line-through opacity-70"
          title="No profile with this name"
        >
          @{name}
        </span>
      ))}

      {!willFanOut && valid.length === 1 && (
        <span className="opacity-60">· fan-out needs ≥2</span>
      )}
    </div>
  );
}

export default MentionPreview;