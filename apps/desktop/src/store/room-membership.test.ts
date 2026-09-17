/**
 * M1.5 Phase 4: room-membership store tests.
 *
 * Pure unit tests for the store + hook API. The actual listRooms
 * integration is Phase 5; these tests pin the contract the query
 * hook will rely on.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  $roomMembership,
  clearRoomMembership,
  getRoomMembershipStore,
  readRoomMembership,
  setRoomMembership,
  useRoomMembership,
} from './room-membership'

describe('setRoomMembership / clearRoomMembership', () => {
  beforeEach(() => {
    $roomMembership.set({})
  })
  afterEach(() => {
    $roomMembership.set({})
  })

  it('starts with an empty map', () => {
    expect($roomMembership.get()).toEqual({})
  })

  it('records a session as belonging to a room', () => {
    setRoomMembership('s1', 'room-A')
    expect($roomMembership.get().s1).toBe('room-A')
  })

  it('is idempotent on identical value (returns false, no churn)', () => {
    setRoomMembership('s1', 'room-A')
    const changed = setRoomMembership('s1', 'room-A')
    expect(changed).toBe(false)
  })

  it('mutates only when the value actually changes (returns true)', () => {
    setRoomMembership('s1', 'room-A')
    const changed = setRoomMembership('s1', 'room-B')
    expect(changed).toBe(true)
    expect($roomMembership.get().s1).toBe('room-B')
  })

  it('clearing (null) is a valid transition', () => {
    setRoomMembership('s1', 'room-A')
    setRoomMembership('s1', null)
    expect($roomMembership.get().s1).toBeNull()
  })

  it('rejects empty sessionId', () => {
    expect(setRoomMembership('', 'room-A')).toBe(false)
    expect($roomMembership.get()).toEqual({})
  })

  it('clearRoomMembership drops the key', () => {
    setRoomMembership('s1', 'room-A')
    clearRoomMembership('s1')
    expect($roomMembership.get().s1).toBeUndefined()
  })

  it('clearRoomMembership is a no-op for unknown session', () => {
    setRoomMembership('s1', 'room-A')
    const before = $roomMembership.get()
    clearRoomMembership('does-not-exist')
    expect($roomMembership.get()).toBe(before)
  })

  it('clearRoomMembership rejects empty sessionId', () => {
    setRoomMembership('s1', 'room-A')
    const before = $roomMembership.get()
    clearRoomMembership('')
    expect($roomMembership.get()).toBe(before)
  })

  it('isolates per-session records', () => {
    setRoomMembership('s1', 'room-A')
    setRoomMembership('s2', 'room-B')
    expect($roomMembership.get().s1).toBe('room-A')
    expect($roomMembership.get().s2).toBe('room-B')
    clearRoomMembership('s1')
    expect($roomMembership.get().s1).toBeUndefined()
    expect($roomMembership.get().s2).toBe('room-B')
  })
})

describe('readRoomMembership (sync read for non-React callers)', () => {
  beforeEach(() => {
    $roomMembership.set({})
  })

  it('returns the room id for a known session', () => {
    setRoomMembership('s1', 'room-A')
    expect(readRoomMembership('s1')).toBe('room-A')
  })

  it('returns null for an unknown session', () => {
    expect(readRoomMembership('unknown')).toBeNull()
  })

  it('returns null for null/undefined input', () => {
    expect(readRoomMembership(null)).toBeNull()
    expect(readRoomMembership(undefined)).toBeNull()
    expect(readRoomMembership('')).toBeNull()
  })

  it('returns null for a session explicitly marked as non-room', () => {
    setRoomMembership('s1', null)
    expect(readRoomMembership('s1')).toBeNull()
  })
})

describe('useRoomMembership (React hook)', () => {
  beforeEach(() => {
    $roomMembership.set({})
  })
  afterEach(() => {
    $roomMembership.set({})
  })

  it('returns null for an unknown session id', () => {
    const { result } = renderHook(() => useRoomMembership('unknown'))
    expect(result.current).toBeNull()
  })

  it('returns null for null session id', () => {
    const { result } = renderHook(() => useRoomMembership(null))
    expect(result.current).toBeNull()
  })

  it('returns the room id after setRoomMembership', () => {
    setRoomMembership('s1', 'room-A')
    const { result } = renderHook(() => useRoomMembership('s1'))
    expect(result.current).toBe('room-A')
  })

  it('re-renders when the membership changes for the watched session only', () => {
    setRoomMembership('s1', 'room-A')
    const { result } = renderHook(() => useRoomMembership('s1'))
    expect(result.current).toBe('room-A')

    // Change a DIFFERENT session's membership: should NOT re-render.
    act(() => setRoomMembership('s2', 'room-B'))
    expect(result.current).toBe('room-A')

    // Change the WATCHED session's membership: SHOULD re-render.
    act(() => setRoomMembership('s1', 'room-Z'))
    expect(result.current).toBe('room-Z')
  })
})

describe('Sentinel: store API surface (Phase 5 query hook contract)', () => {
  it('exports the symbols the future listRooms hook will call', () => {
    expect(typeof setRoomMembership).toBe('function')
    expect(typeof clearRoomMembership).toBe('function')
    expect(typeof readRoomMembership).toBe('function')
    expect(typeof useRoomMembership).toBe('function')
    expect(getRoomMembershipStore()).toBeDefined()
  })
})
