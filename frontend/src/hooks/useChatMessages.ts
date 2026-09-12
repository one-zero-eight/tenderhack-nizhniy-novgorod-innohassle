import { useQuery } from '@tanstack/react-query'
import { fetchChatMessages } from '@/api/chat'
import { toMessageView, type MessageView } from '@/lib/chat-view'
import { chatMessagesQueryKey } from '@/hooks/useStreamMessage'

/**
 * Loads the history for a chat from `GET /chats/{id}/messages`, following the
 * `has_more` / `next_sequence` cursor to fetch every page.
 *
 * Live replies arrive via the SSE stream in `useStreamMessage`, so this query
 * is refreshed on demand (after a stream completes, on mount, and on window
 * focus) rather than polled.
 */
export function useChatMessages(chatId: string | undefined) {
  return useQuery<MessageView[], Error>({
    queryKey: chatMessagesQueryKey(chatId ?? ''),
    queryFn: async () => {
      const all: MessageView[] = []
      let afterSequence = 0
      // Guard against an unbounded loop if the backend misbehaves.
      for (let page = 0; page < 100; page += 1) {
        const result = await fetchChatMessages(chatId as string, afterSequence)
        all.push(...result.items.map(toMessageView))
        if (!result.has_more) break
        afterSequence = result.next_sequence
      }
      return all
    },
    enabled: !!chatId,
  })
}
