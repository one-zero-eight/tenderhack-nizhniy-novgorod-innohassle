/**
 * Hand-rule API client.
 *
 * Hand-rules live in the ML service under `/ml-api/handrules` and are public
 * (no auth). They pair an example user question with the instruction the agent
 * should follow when a similar question arrives.
 */

const API_ORIGIN = import.meta.env.VITE_API_URL ?? '/api'

/** Base for the hand-rule endpoints, independent of the `/api` prefix. */
const HANDRULES = `${API_ORIGIN}/ml-api/handrules`

/** A stored hand-rule. */
export interface HandRule {
  id: string
  /** Example user question the rule is matched against. */
  user_message: string
  /** What the agent should do for such a question. */
  instructions: string
  created_at?: string | null
  updated_at?: string | null
}

/** Payload for creating a hand-rule. */
export interface HandRuleInput {
  user_message: string
  instructions: string
}

/** Payload for updating a hand-rule; both fields are optional. */
export type HandRulePatch = Partial<HandRuleInput>

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message
  } catch {
    // Non-JSON error body.
  }
  return 'Не удалось выполнить запрос'
}

/** Lists hand-rules, newest first. */
export async function fetchHandRules(limit = 200): Promise<HandRule[]> {
  const response = await fetch(`${HANDRULES}?limit=${limit}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(await readError(response))
  return (await response.json()) as HandRule[]
}

/** Creates a hand-rule and returns it. */
export async function createHandRule(input: HandRuleInput): Promise<HandRule> {
  const response = await fetch(HANDRULES, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) throw new Error(await readError(response))
  return (await response.json()) as HandRule
}

/** Updates a hand-rule by id and returns the updated rule. */
export async function updateHandRule(ruleId: string, patch: HandRulePatch): Promise<HandRule> {
  const response = await fetch(`${HANDRULES}/${encodeURIComponent(ruleId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!response.ok) throw new Error(await readError(response))
  return (await response.json()) as HandRule
}

/** Deletes a hand-rule by id. */
export async function deleteHandRule(ruleId: string): Promise<void> {
  const response = await fetch(`${HANDRULES}/${encodeURIComponent(ruleId)}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(await readError(response))
}

/**
 * Finds the rules most similar to a question. Used by the search box; the
 * backend ranks by meaning rather than exact text.
 */
export async function searchHandRules(query: string, k = 20): Promise<HandRule[]> {
  const params = new URLSearchParams({ q: query, k: String(k) })
  const response = await fetch(`${HANDRULES}/search?${params.toString()}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(await readError(response))
  return (await response.json()) as HandRule[]
}

/* ----------------------------------------------------------------- fuzzy search */

/** Lowercases and strips punctuation/diacritics so matching is forgiving. */
function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/[ё]/g, 'е')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Splits a query into normalized terms. */
function terms(query: string): string[] {
  return normalize(query).split(' ').filter(Boolean)
}

/**
 * Scores a rule against the query terms. Returns `0` when nothing matches.
 *
 * A term counts as a match when it is a substring of either field, when it is a
 * prefix of any word (so typing «парол» matches «пароль»), or when the term and
 * a word share a long-enough prefix (so «ошибка» matches «ошибку»).
 */
function scoreRule(rule: HandRule, queryTerms: string[]): number {
  if (queryTerms.length === 0) return 1

  const message = normalize(rule.user_message)
  const instructions = normalize(rule.instructions)
  const words = [...message.split(' '), ...instructions.split(' ')]

  let score = 0
  for (const term of queryTerms) {
    if (message.includes(term)) score += 3
    else if (instructions.includes(term)) score += 2
    else if (words.some((word) => word.startsWith(term))) score += 1
    else if (words.some((word) => sharesStem(term, word))) score += 1
    else return 0 // a term with no match anywhere disqualifies the rule
  }
  return score
}

/**
 * Whether two words share a long enough prefix to be considered the same stem.
 *
 * Russian inflects endings («ошибка» / «ошибку»), so exact prefix matching is
 * too strict. Longer words need a 4-character common prefix; short words (like
 * «рэм» / «рэма») match when the term is a prefix of the word.
 */
function sharesStem(term: string, word: string): boolean {
  const min = Math.min(term.length, word.length)
  if (min < 3) return false
  let common = 0
  while (common < min && term[common] === word[common]) common += 1
  // Require the whole shorter word to be consumed when it is short.
  return min < 4 ? common === min : common >= 4
}

/**
 * Filters and ranks rules against a free-text query, entirely client-side.
 * Returns the full list unchanged when the query is empty.
 */
export function fuzzyMatchHandRules(rules: HandRule[], query: string): HandRule[] {
  const queryTerms = terms(query)
  if (queryTerms.length === 0) return rules

  return rules
    .map((rule) => ({ rule, score: scoreRule(rule, queryTerms) }))
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score)
    .map((entry) => entry.rule)
}
