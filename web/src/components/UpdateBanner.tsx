/**
 * UpdateBanner — sidebar banner that surfaces dashboard version drift.
 *
 * Polls /api/runtime/version on mount and on a 5-minute interval. When
 * `drift` is true the banner shows the running vs. disk commit short SHAs
 * and a manual restart hint (no auto-restart: the dashboard is owned by
 * the same process whose restart we are advertising, so a self-restart
 * would race with the user's next click).
 *
 * Non-git installs return drift=false, so this is a no-op everywhere
 * except checkout-bearing installs.
 */
import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { RuntimeVersionResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 5 * 60 * 1000; // 5 min

export function UpdateBanner(): React.JSX.Element | null {
  const [version, setVersion] = useState<RuntimeVersionResponse | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const lastFetchRef = useRef(0);

  const fetchVersion = useCallback(async () => {
    // Throttle: skip if a fetch ran <5s ago (e.g. component remount under StrictMode)
    const now = Date.now();
    if (now - lastFetchRef.current < 5000) return;
    lastFetchRef.current = now;
    try {
      const v = await api.getRuntimeVersion();
      setVersion(v);
      // Reset the dismissed flag when drift resolves (rare but cheap to handle).
      if (!v.drift) setDismissed(false);
    } catch {
      // Network blip — keep last known state, do nothing visible.
    }
  }, []);

  useEffect(() => {
    void fetchVersion();
    const id = window.setInterval(() => void fetchVersion(), POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [fetchVersion]);

  if (!version || !version.drift || dismissed) return null;

  return (
    <div
      role="status"
      data-testid="update-banner"
      className={cn(
        "mx-2 mb-2 rounded-md border border-amber-300/40",
        "bg-amber-50/30 dark:bg-amber-900/20",
        "px-2.5 py-1.5 text-[11px] leading-snug",
        "text-amber-900 dark:text-amber-100",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="font-medium">Restart required</div>
          <div className="mt-0.5 font-mono text-[10px] text-amber-800/80 dark:text-amber-200/80">
            <span title="running commit">{version.running ?? "?"}</span>
            {" → "}
            <span title="disk commit">{version.disk ?? "?"}</span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss update banner"
          className={cn(
            "shrink-0 rounded p-0.5 text-amber-900/60",
            "hover:bg-amber-200/40 hover:text-amber-900",
            "dark:text-amber-200/60 dark:hover:bg-amber-800/40",
          )}
        >
          ×
        </button>
      </div>
      <p className="mt-1 text-[10px] opacity-90">{version.hint}</p>
    </div>
  );
}

export default UpdateBanner;