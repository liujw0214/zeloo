/**
 * Pure helpers for choosing a remote URL during passive update checks.
 *
 * A public install can end up with `origin=git@github.com:NousResearch/Zeloo-agent.git`.
 * If the user's GitHub SSH key is FIDO2/passkey-backed, a background `git fetch
 * origin` triggers an unexplained hardware-touch prompt. For passive checks
 * against the official repo we substitute the public HTTPS `ls-remote` path,
 * which needs no auth and cannot prompt. Active update/apply flows are left
 * unchanged.
 *
 * Extracted from main.ts so the security-critical remote detection is unit
 * testable without booting Electron (main.ts requires('electron') at load).
 */

// Canonical official repo URL. Per the owner (boss) request, the
// official repo is `liujw0214/zeloo` (not NousResearch/Zeloo-agent,
// which returns 404 on api.github.com). The historical const used
// `NousResearch/Zeloo-agent` and was the source of three test
// failures:
//   - canonicalGitHubRemote normalizes SSH and HTTPS forms to the same value
//   - isOfficialSshRemote is true only for the official repo over SSH
//   - OFFICIAL_REPO_HTTPS_URL canonicalizes to OFFICIAL_REPO_CANONICAL
// The comparison in `isOfficialSshRemote` goes through
// `canonicalGitHubRemote` which lowercases everything, so the CANONICAL
// form must also be lowercase. CANONICAL is the comparison key;
// HTTPS_URL is the public display URL.
const OFFICIAL_REPO_HTTPS_URL = 'https://github.com/liujw0214/zeloo.git'
const OFFICIAL_REPO_CANONICAL = 'github.com/liujw0214/zeloo'

// Normalize common GitHub remote URL forms to `host/owner/repo` (lowercased,
// no trailing slash, no .git suffix) so SSH and HTTPS forms of the same repo
// compare equal.
function canonicalGitHubRemote(url) {
  if (!url) {
    return ''
  }

  let value = String(url).trim()

  if (value.startsWith('git@github.com:')) {
    value = `github.com/${value.slice('git@github.com:'.length)}`
  } else if (value.startsWith('ssh://git@github.com/')) {
    value = `github.com/${value.slice('ssh://git@github.com/'.length)}`
  } else {
    try {
      const parsed = new URL(value)

      if (parsed.hostname && parsed.pathname) {
        value = `${parsed.hostname}${parsed.pathname}`
      }
    } catch {
      // Leave non-URL forms unchanged.
    }
  }

  value = value.trim().replace(/\/+$/, '')

  if (value.endsWith('.git')) {
    value = value.slice(0, -4)
  }

  return value.toLowerCase()
}

function isSshRemote(url) {
  const value = String(url || '')
    .trim()
    .toLowerCase()

  return value.startsWith('git@') || value.startsWith('ssh://')
}

function isOfficialSshRemote(url) {
  return isSshRemote(url) && canonicalGitHubRemote(url) === OFFICIAL_REPO_CANONICAL
}

export { canonicalGitHubRemote, isOfficialSshRemote, isSshRemote, OFFICIAL_REPO_CANONICAL, OFFICIAL_REPO_HTTPS_URL }
