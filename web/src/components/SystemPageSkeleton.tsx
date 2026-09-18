import * as React from "react";
import { AsciiSkeleton } from "@nous-research/ui/ui/components/ascii";

import { Card, CardContent } from "@nous-research/ui/ui/components/card";

/**
 * Suspense fallback for /system. Mirrors the real SystemPage section layout so
 * the page doesn't pop from a blank spinner to the full dashboard — first paint
 * matches the final shape, then the chunk arrives and replaces it.
 *
 * Animated ASCII blocks pulse via the AsciiSkeleton component so screen
 * readers (and human eyes) perceive forward progress instead of a freeze.
 */
export function SystemPageSkeleton(): React.JSX.Element {
  return (
    <div
      className="flex flex-col gap-3"
      aria-busy="true"
      aria-live="polite"
      aria-label="Loading System page"
    >
      {/* Top: page title + header actions */}
      <div className="flex items-center justify-between gap-2">
        <h1 className="font-mondwest text-display text-xl tracking-wider">
          System
        </h1>
        <div className="flex items-center gap-2">
          <AsciiSkeleton cols={16} rows={1} />
        </div>
      </div>

      {/* Host / System stats card */}
      <Card>
        <CardContent className="py-4">
          <div className="mb-3 flex items-center justify-between">
            <AsciiSkeleton cols={6} rows={1} />
            <AsciiSkeleton cols={14} rows={1} />
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="flex flex-col gap-1">
                <AsciiSkeleton cols={6} rows={1} />
                <AsciiSkeleton cols={14} rows={1} />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Update + Nous Portal + Tool gateway routing */}
      <Card>
        <CardContent className="flex flex-col gap-3 py-4">
          <div className="flex items-center justify-between">
            <AsciiSkeleton cols={10} rows={1} />
            <AsciiSkeleton cols={14} rows={1} />
          </div>
          <div className="flex items-center justify-between">
            <AsciiSkeleton cols={12} rows={1} />
            <AsciiSkeleton cols={16} rows={1} />
          </div>
          <div className="flex items-center justify-between">
            <AsciiSkeleton cols={8} rows={1} />
            <AsciiSkeleton cols={18} rows={1} />
          </div>
        </CardContent>
      </Card>

      {/* Gateway controls */}
      <Card>
        <CardContent className="flex items-center justify-between py-4">
          <div className="flex flex-col gap-1">
            <AsciiSkeleton cols={8} rows={1} />
            <AsciiSkeleton cols={20} rows={1} />
          </div>
          <div className="flex items-center gap-2">
            <AsciiSkeleton cols={10} rows={1} />
            <AsciiSkeleton cols={10} rows={1} />
            <AsciiSkeleton cols={8} rows={1} />
          </div>
        </CardContent>
      </Card>

      {/* Memory + provider */}
      <Card>
        <CardContent className="flex flex-col gap-3 py-4">
          <div className="flex items-center justify-between">
            <AsciiSkeleton cols={8} rows={1} />
            <AsciiSkeleton cols={14} rows={1} />
          </div>
          <div className="flex items-center justify-between">
            <AsciiSkeleton cols={20} rows={1} />
            <AsciiSkeleton cols={10} rows={1} />
          </div>
          <div className="flex items-center justify-between">
            <AsciiSkeleton cols={24} rows={1} />
          </div>
          <div className="flex items-center gap-2">
            <AsciiSkeleton cols={12} rows={1} />
            <AsciiSkeleton cols={12} rows={1} />
            <AsciiSkeleton cols={10} rows={1} />
          </div>
        </CardContent>
      </Card>

      {/* Credential pool + Operations + Backup */}
      <Card>
        <CardContent className="flex flex-col gap-3 py-4">
          <div className="flex items-center justify-between">
            <AsciiSkeleton cols={16} rows={1} />
            <AsciiSkeleton cols={8} rows={1} />
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="flex flex-col gap-1 rounded-md border border-current/10 p-2"
              >
                <AsciiSkeleton cols={6} rows={1} />
                <AsciiSkeleton cols={14} rows={1} />
                <AsciiSkeleton cols={10} rows={1} />
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <AsciiSkeleton key={i} cols={8} rows={1} />
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Backup + restore */}
      <Card>
        <CardContent className="flex flex-col gap-3 py-4">
          <div className="flex items-center justify-between">
            <AsciiSkeleton cols={12} rows={1} />
            <AsciiSkeleton cols={10} rows={1} />
          </div>
          <div className="flex flex-col gap-2">
            <AsciiSkeleton cols={24} rows={1} />
            <AsciiSkeleton cols={20} rows={1} />
            <AsciiSkeleton cols={16} rows={1} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default SystemPageSkeleton;