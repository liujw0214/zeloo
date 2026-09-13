import { describe, expect, it } from 'vitest'

import {
  normalizeZELOOOpenString,
  pathFromZELOODeepLink,
  pathFromOpenDeepLink,
  resolveZELOOOpenPath
} from './Zeloo-open-target'

describe('normalizeZELOOOpenString', () => {
  it('accepts hash-router paths and strips a leading hash', () => {
    expect(normalizeZELOOOpenString('/index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeZELOOOpenString('#/index-network/intent/1')).toBe('/index-network/intent/1')
  })

  it('maps plugin-scoped Zeloo:// deep links to the same path', () => {
    expect(normalizeZELOOOpenString('Zeloo://index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeZELOOOpenString('Zeloo://index-network/intent/1?focus=true')).toBe(
      '/index-network/intent/1?focus=true'
    )
  })

  it('maps Zeloo://open/… deep links by stripping the open host', () => {
    expect(normalizeZELOOOpenString('Zeloo://open/index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeZELOOOpenString('Zeloo://open/settings/plugins')).toBe('/settings/plugins')
  })

  it('rejects reserved Zeloo kinds and unsafe paths', () => {
    expect(normalizeZELOOOpenString('Zeloo://blueprint/morning-brief')).toBeNull()
    expect(normalizeZELOOOpenString('Zeloo://plugin/install')).toBeNull()
    expect(normalizeZELOOOpenString('https://example.com/x')).toBeNull()
    expect(normalizeZELOOOpenString('/../etc/passwd')).toBeNull()
    expect(normalizeZELOOOpenString('index-network')).toBeNull()
  })
})

describe('resolveZELOOOpenPath', () => {
  it('merges structured path + params', () => {
    expect(resolveZELOOOpenPath({ path: '/index-network/intent/1', params: { focus: 'true' } })).toBe(
      '/index-network/intent/1?focus=true'
    )
  })

  it('resolves href the same as a bare string', () => {
    expect(resolveZELOOOpenPath({ href: 'Zeloo://index-network/intent/1' })).toBe('/index-network/intent/1')
  })
})

describe('pathFromZELOODeepLink', () => {
  it('builds the navigate path from a plugin-scoped deep-link payload', () => {
    expect(pathFromZELOODeepLink('index-network', 'intent/1')).toBe('/index-network/intent/1')
  })

  it('builds the navigate path from Zeloo://open/… payloads', () => {
    expect(pathFromOpenDeepLink('index-network/intent/1')).toBe('/index-network/intent/1')
    expect(pathFromZELOODeepLink('open', 'agent/42')).toBe('/agent/42')
  })

  it('ignores reserved kinds', () => {
    expect(pathFromZELOODeepLink('blueprint', 'morning-brief')).toBeNull()
    expect(pathFromZELOODeepLink('plugin', 'install')).toBeNull()
  })
})
