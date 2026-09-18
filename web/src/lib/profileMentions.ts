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