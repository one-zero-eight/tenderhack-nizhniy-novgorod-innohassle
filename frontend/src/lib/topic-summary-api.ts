/**
 * Topic summary API client.
 *
 * The ML service generates a Markdown summary of the recurring problems in a
 * statistics topic. It lives under `/ml-api/stats/...` and is public (no auth).
 */

import type { SchemaTopicSummaryStatus } from '@/api/types'

const API_ORIGIN = import.meta.env.VITE_API_URL ?? '/api'

/** Base for the statistics endpoints. */
const STATS = `${API_ORIGIN}/ml-api/stats`

/**
 * Lifecycle of a topic summary:
 * - `ready`    — up to date
 * - `outdated` — new feedback arrived, a recompute is running
 * - `pending`  — feedback exists but no summary has been generated yet
 * - `none`     — the topic has no feedback at all
 */
export type TopicSummaryStatus = SchemaTopicSummaryStatus['status']

/**
 * Loads the AI summary for a topic. Returns `summary: null` when nothing has
 * been generated yet, which callers should render as a placeholder.
 */
export async function fetchTopicSummary(topic: string): Promise<SchemaTopicSummaryStatus> {
  const response = await fetch(`${STATS}/topics/${encodeURIComponent(topic)}/summary`, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    let message = 'Не удалось загрузить сводку'
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') message = body.detail
    } catch {
      // Non-JSON error body.
    }
    throw new Error(message)
  }
  return (await response.json()) as SchemaTopicSummaryStatus
}
