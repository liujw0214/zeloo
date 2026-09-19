/**
 * Profile mention parser for the @xxx syntax inside chat prompts.
 *
 * Matches tokens like `@coder`, `@coder-2`, `@research_pro` — must start with
 * a letter/digit, followed by 0–63 of [a-z0-9_-]. Same regex the backend
 * `group_chat.py` uses to whitelist profile names, so anything that
 * round-trips through here is guaranteed to be a legal CLI profile arg.
 *
 * Returns the unique ordered list of valid + unknown mentions — dedup
 * preserves first occurrence so the host pick stays deterministic.
 */
export interface MentionParseResult {
  /** Mention tokens that match a known profile name. Ordered, deduped. */
  valid: string[];
  /** Mention tokens not in the known profile list (typos / deleted profiles). */
  unknown: string[];
  /** All raw mention tokens (valid + unknown), useful for highlight. */
  all: string[];
}

const MENTION_RE = /@([a-z0-9][a-z0-9_-]{0,63})/gi;

export function parseProfileMentions(
  text: string,
  knownNames: Iterable<string>,
): MentionParseResult {
  const known = new Set<string>();
  for (const n of knownNames) known.add(n.toLowerCase());

  const valid: string[] = [];
  const unknown: string[] = [];
  const all: string[] = [];
  const seenValid = new Set<string>();
  const seenUnknown = new Set<string>();

  for (const m of text.matchAll(MENTION_RE)) {
    const tok = m[1].toLowerCase();
    if (all.includes(tok)) continue; // dedup everything by first occurrence
    all.push(tok);
    if (known.has(tok)) {
      if (!seenValid.has(tok)) {
        seenValid.add(tok);
        valid.push(tok);
      }
    } else {
      if (!seenUnknown.has(tok)) {
        seenUnknown.add(tok);
        unknown.push(tok);
      }
    }
  }
  return { valid, unknown, all };
}

/**
 * Strip all valid `@xxx` mentions from the prompt so the host / workers see a
 * clean natural-language question instead of echo-tagging themselves.
 * Unknown mentions are left in place — they may be intentional ("@bob who is
 * not a profile") and shouldn't be silently dropped.
 */
export function stripValidMentions(text: string, valid: string[]): string {
  if (valid.length === 0) return text;
  // Build a single alternation regex once; case-insensitive match so the
  // user's original casing for the rest of the message is preserved.
  const names = valid.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`@(?:${names.join("|")})\\b`, "gi");
  // Collapse multiple spaces that the strip may have left behind.
  return text.replace(re, "").replace(/[ \t]{2,}/g, " ").replace(/^[ \t]+|[ \t]+$/gm, "");
}

/** Pick a sensible host when the user only mentioned workers. */
export function chooseHost(
  mentioned: string[],
  defaultProfileName: string | undefined,
  knownNames: Iterable<string>,
): string {
  if (mentioned.length === 0) return defaultProfileName ?? "";
  // First mentioned becomes the host so the natural reading order wins.
  // Falls back to the dashboard default if the mentioned set is somehow empty.
  const first = mentioned[0];
  const known = new Set<string>(knownNames);
  if (known.has(first)) return first;
  return defaultProfileName ?? "";
}

/** Workers = every mention except the host. */
export function workersFromMentions(
  mentioned: string[],
  host: string,
): string[] {
  return mentioned.filter((m) => m !== host);
}

// ---------------------------------------------------------------------------
// `@agent` meta-mention
// ---------------------------------------------------------------------------
// `@agent` (case-insensitive, NOT followed by another name char so @agent42
// is left as literal text) triggers the multi-agent fan-out pipeline instead
// of a normal single-agent run. Optional inline options:
//
//   @agent                              — bare; backend resolves via known
//                                          profiles (first alphabetical = host,
//                                          rest = workers, capped at MAX_WORKERS)
//   @agent(host=<profile>)              — explicit host
//   @agent(workers=a,b,c)               — explicit workers
//   @agent(host=<profile>, workers=a,b,c) — both
//
// Only the FIRST `@agent` per prompt counts — later occurrences are left as
// literal text. Mirrors the backend's `extract_agent_mention` so the preview
// and the eventual dispatch agree.

export interface AgentMention {
  /** Whether `@agent` was found in the prompt. */
  present: boolean;
  /** Explicit host from `host=<profile>`, undefined when bare / workers-only. */
  host?: string;
  /** Explicit workers from `workers=a,b,c`, undefined when bare / host-only. */
  workers?: string[];
  /** Cleaned prompt with the `@agent(...)` token stripped. */
  cleanedPrompt: string;
  /** True if any inline option has a syntactically valid profile name regex. */
  optionsValid: boolean;
}

const AGENT_MENTION_BOUNDARY_RE =
  /@agent(?![a-z0-9_-])((?:\(\s*([^)]*?)\s*\))?)/i;

const PROFILE_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

/**
 * Tokenizer that respects `workers=a,b,c` (does NOT split on commas inside the value).
 *
 * Returns:
 *   hostSeen: true if a `host=<value>` clause was provided at all (even when value was invalid)
   host:      the value if it passed PROFILE_NAME_RE, else undefined
   workers:   the comma-split worker list if `workers=` was provided, else undefined
 *
 * The `hostSeen` flag lets `parseAgentMention` distinguish "no host= clause" from
 * "host= clause with an invalid value" — both have host===undefined but only the latter
 * should flip optionsValid to false.
 */
function parseAgentOptions(
  raw: string,
): { hostSeen: boolean; host?: string; workers?: string[] } {
  const out: { hostSeen: boolean; host?: string; workers?: string[] } = {
    hostSeen: false,
  };
  if (!raw) return out;
  let i = 0;
  while (i < raw.length) {
    while (i < raw.length && (raw[i] === ' ' || raw[i] === ',')) i++;
    if (i >= raw.length) break;
    const eq = raw.indexOf('=', i);
    if (eq === -1) break;
    const key = raw.slice(i, eq).trim().toLowerCase();
    i = eq + 1;
    let j = i;
    while (j < raw.length) {
      if (raw[j] === ',') {
        let k = j + 1;
        while (k < raw.length && raw[k] === ' ') k++;
        if (k < raw.length && /[a-z]/.test(raw[k])) {
          const nextEq = raw.indexOf('=', k);
          if (nextEq !== -1 && nextEq - k < 32) {
            const candidate = raw.slice(k, nextEq).trim().toLowerCase();
            if (candidate === 'host' || candidate === 'workers') break;
          }
        }
      }
      j++;
    }
    const value = raw.slice(i, j).trim();
    if (key === 'host') {
      out.hostSeen = true;
      if (PROFILE_NAME_RE.test(value)) {
        out.host = value;
      }
    } else if (key === 'workers') {
      // We collect all comma-separated tokens, even ones that fail PROFILE_NAME_RE
      // — the caller uses optionsValid to surface the bad-name chip in the preview.
      out.workers = value
        .split(',')
        .map((w) => w.trim())
        .filter((w) => w.length > 0);
    }
    i = j + 1;
  }
  return out;
}

/**
 * Detect the FIRST `@agent(...)` meta-mention in `text`. Returns a fully
 * populated `AgentMention` (with `present=false`) when no token is found so
 * callers can `if (agent.present)` without nil checks.
 */
export function parseAgentMention(text: string): AgentMention {
  const empty: AgentMention = {
    present: false,
    cleanedPrompt: text,
    optionsValid: true,
  };
  if (!text) return empty;
  // Quick reject — cheaper than running the regex on every keystroke.
  if (!/[Aa][Gg][Ee][Nn][Tt]/.test(text)) return empty;

  const m = AGENT_MENTION_BOUNDARY_RE.exec(text);
  if (!m) return empty;

  const optsRaw = m[2] ?? '';
  const opts = parseAgentOptions(optsRaw);

  // `optionsValid` is false when the user EXPLICITLY wrote a `host=` clause with
  // a value that fails PROFILE_NAME_RE, or any `workers=` token fails the regex.
  // A bare `@agent` (no options) keeps optionsValid=true.
  const hostOk = !opts.hostSeen || (opts.host !== undefined);
  const workersOk = !opts.workers || opts.workers.every((w) => PROFILE_NAME_RE.test(w));
  const optionsValid = hostOk && workersOk;

  const cleaned = (
    text.slice(0, m.index) +
    text.slice(m.index + m[0].length)
  )
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/^[ \t]+|[ \t]+$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  return {
    present: true,
    host: opts.host,
    workers: opts.workers,
    cleanedPrompt: cleaned,
    optionsValid,
  };
}

/**
 * Client-side resolver: turn an `AgentMention` into a `(host, workers)`
 * tuple ready to publish as a `GroupChatPreset`. When the prompt only has
 * a bare `@agent`, the host is the first profile alphabetically and the
 * workers are the remaining profiles (capped at 8, matching backend).
 *
 * Returns null when `agent.present` is false, when options are syntactically
 * invalid, when fewer than 2 distinct profiles are known, or when the
 * explicit host doesn't exist in the known set.
 */
export function resolveAgentFanOut(
  agent: AgentMention,
  knownNames: Iterable<string>,
  defaultProfile: string | undefined,
): { prompt: string; host: string; workers: string[] } | null {
  if (!agent.present || !agent.optionsValid) return null;

  const known = Array.from(new Set(Array.from(knownNames, (n) => n.toLowerCase())));
  if (known.length < 2) return null;

  let host: string;
  if (agent.host) {
    if (!known.includes(agent.host.toLowerCase())) return null;
    host = agent.host;
  } else {
    host = defaultProfile && known.includes(defaultProfile.toLowerCase())
      ? defaultProfile
      : known[0];
  }

  let workers: string[];
  if (agent.workers && agent.workers.length > 0) {
    workers = agent.workers
      .map((w) => w.toLowerCase())
      .filter((w) => known.includes(w) && w !== host);
    if (workers.length === 0) return null;
  } else {
    workers = known.filter((w) => w !== host).slice(0, 8);
    if (workers.length === 0) return null;
  }

  return {
    prompt: agent.cleanedPrompt,
    host,
    workers,
  };
}
