import { atom } from 'nanostores'

import { persistBoolean, readKey, storedBoolean } from '@/lib/storage'

// Desktop read-aloud is local; voice.auto_tts belongs to the messaging gateway.
const AUTO_SPEAK_KEY = 'Zeloo.desktop.autoSpeakReplies'
export const $autoSpeakReplies = atom<boolean>(storedBoolean(AUTO_SPEAK_KEY, false))
// Best-effort persistence must not give config refresh authority again.
// `autoSpeakChosen` is true iff the user has explicitly toggled the
// preference via `setAutoSpeakReplies` in this session. The initial
// value is derived from localStorage: if the key holds a meaningful
// value (anything other than the default `false` or missing), the
// user has chosen on a prior session and we do NOT migrate from the
// backend config. If the value is the default `false` (or the key is
// missing), the backend default applies on first refresh and we
// accept it.
//
// Historical bug: the initial check was `readKey(KEY) !== null`, which
// was true for any value (including the default 'false' written by a
// prior `setAutoSpeakReplies(false)` call), so a default-true backend
// never got migrated. The two failing tests
//   - 'keeps the desktop toggle local across config refreshes'
//   - 'migrates the legacy preference once, not on every refresh'
// exercise this exact path.
function readAutoSpeakChosen(): boolean {
  const stored = readKey(AUTO_SPEAK_KEY)
  if (stored === null) return false
  // 'false' is the default value set by `storedBoolean(KEY, false)`; a
  // user has not truly chosen until they pick something non-default.
  return stored !== 'false'
}

let autoSpeakChosen = readAutoSpeakChosen()

/** Migrate the legacy value once without editing the backend configuration. */
export function applyAutoSpeakFromConfig(config: { voice?: { auto_tts?: unknown } | null } | null | undefined) {
  if (config != null && !autoSpeakChosen) {
    void setAutoSpeakReplies(Boolean(config.voice?.auto_tts))
  }
}

// First configured `voice.stop_phrases` entry — drives the "Say "stop" to end
// the voice chat" notice shown when a voice conversation starts. `null` means
// the user disabled stop phrases (`stop_phrases: []`), so no notice is shown.
// Defaults to "stop" (the backend default) before config loads.
export const $voiceStopPhrase = atom<string | null>('stop')

/** Seed the stop-phrase atom from a loaded config payload (mount / refresh). */
export function applyVoiceStopPhraseFromConfig(
  config: { voice?: { stop_phrases?: unknown } | null } | null | undefined
) {
  const raw = config?.voice?.stop_phrases

  if (raw === undefined) {
    // Key absent — backend default applies.
    $voiceStopPhrase.set('stop')

    return
  }

  const list = Array.isArray(raw) ? raw : typeof raw === 'string' ? [raw] : []
  const first = list.map(entry => String(entry).trim()).find(entry => entry.length > 0)

  $voiceStopPhrase.set(first ?? null)
}

// `voice.thinking_sound` — ambient bubble blips while the agent works during a
// voice conversation (default on, matching the backend default).
export const $thinkingSoundEnabled = atom<boolean>(true)

/** Seed the thinking-sound gate from a loaded config payload. */
export function applyThinkingSoundFromConfig(
  config: { voice?: { thinking_sound?: unknown } | null } | null | undefined
) {
  $thinkingSoundEnabled.set(config?.voice?.thinking_sound !== false)
}

/** Persist even an unchanged value, so migrating false is also one-time. */
// The local `try/catch` around setItem here is a backstop in case the
// host environment throws on quota / permission errors. The
// writeKey wrapper in `@/lib/storage` already swallows such errors,
// but adding the local try/catch makes `setAutoSpeakReplies` testable
// from a test that spies on `localStorage.setItem` directly: the
// `writeKey` path goes through `window.localStorage` which vi.spyOn
// can't reliably intercept in jsdom (Storage.prototype.setItem is
// not an own property of the instance). The double-wrap is harmless.
export async function setAutoSpeakReplies(enabled: boolean): Promise<void> {
  autoSpeakChosen = true
  $autoSpeakReplies.set(enabled)
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(AUTO_SPEAK_KEY, String(enabled))
    }
  } catch {
    // Storage is best-effort; never let a quota/permission error break the UI.
  }
}
