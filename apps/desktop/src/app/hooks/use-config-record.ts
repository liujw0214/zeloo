import { useQuery } from '@tanstack/react-query'

import { getZELOOConfigRecord, type ProfileScope, profileScopeKey } from '@/Zeloo'
import { queryClient, writeCache } from '@/lib/query-client'
import type { ZELOOConfigRecord } from '@/types/Zeloo'

// One shared cache for the whole profile config record (`GET /api/config`).
// Every settings surface (MCP, model, config) reads and writes through this key
// so a save in one shows in the others, and revisiting a tab paints the cache
// instead of blanking on a fresh fetch.
//
// Distinct from session/hooks/use-Zeloo-config.ts, which is side-effecting —
// it pushes personality/cwd/voice/… into the session stores for live chat.
export const ZELOO_CONFIG_KEY = ['Zeloo-config-record'] as const

// Per-scope cache key. The base key (no suffix) is the app-wide active
// profile, unchanged for every caller that passes nothing. An explicit scope —
// the Capabilities scope selector configuring ANOTHER profile, possibly on
// another registered gateway — gets its own suffixed key so switching the
// selector refetches and never paints stale cross-profile config (the
// AGENTS.md scope-in-key rule). profileScopeKey folds a remote pin's
// connection id into the suffix, so two gateways' same-named profiles never
// share a cache row.
export const ZELOOConfigKey = (profile?: ProfileScope) =>
  profile == null ? ZELOO_CONFIG_KEY : ([...ZELOO_CONFIG_KEY, profileScopeKey(profile)] as const)

// staleTime 0 → serve cache instantly, background-revalidate on every mount.
// `profile` scopes both the query key and the fetch; omitting it preserves the
// exact app-wide behavior (base key, `profileScoped(undefined)` fallback).
export const useZELOOConfigRecord = (profile?: ProfileScope) =>
  useQuery({
    queryKey: ZELOOConfigKey(profile),
    // null/undefined both mean "no override" → fetch with undefined so
    // capabilityScoped falls back to the app-wide active profile (passing null
    // would wrongly target the primary backend).
    queryFn: () => getZELOOConfigRecord(profile ?? undefined),
    staleTime: 0
  })

// setZELOOConfigCache writes the app-wide (base-key) record. Pass a profile to
// write the suffixed per-profile cache instead — keeps the selector's optimistic
// write-through landing on the same key its query reads.
export const setZELOOConfigCache = writeCache<ZELOOConfigRecord>(ZELOO_CONFIG_KEY)
export const ZELOOConfigCacheWriter = (profile?: ProfileScope) =>
  writeCache<ZELOOConfigRecord>(ZELOOConfigKey(profile))

export const invalidateZELOOConfig = (profile?: ProfileScope) =>
  queryClient.invalidateQueries({ queryKey: ZELOOConfigKey(profile) })
