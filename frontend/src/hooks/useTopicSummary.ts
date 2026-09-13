import { useQuery } from '@tanstack/react-query'
import { fetchTopicSummary } from '@/lib/topic-summary-api'

export const topicSummaryQueryKey = (topic: string) => ['topic-summary', topic] as const

/**
 * Loads the AI summary of a topic's recurring problems.
 *
 * Summaries are recomputed in the background, so the response can be `pending`
 * or `outdated`; keep refetching occasionally to pick up a fresh one.
 */
export function useTopicSummary(topic: string | undefined) {
  return useQuery({
    queryKey: topicSummaryQueryKey(topic ?? ''),
    queryFn: () => fetchTopicSummary(topic as string),
    enabled: !!topic,
    staleTime: 1000 * 60 * 5,
    // Poll while a summary is still being generated or recomputed.
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'pending' || status === 'outdated' ? 10_000 : false
    },
  })
}
