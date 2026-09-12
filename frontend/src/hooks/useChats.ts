import { useQuery } from '@tanstack/react-query'
import { fetchChats } from '@/api/chat'
import { toChatView, type ChatView } from '@/lib/chat-view'

export const chatsQueryKey = ['chats'] as const

/**
 * Loads the current user's chats from `GET /chats`.
 */
export function useChats() {
  return useQuery<ChatView[], Error>({
    queryKey: chatsQueryKey,
    queryFn: async () => {
      const page = await fetchChats({ limit: 100 })
      return page.items.map((chat) => toChatView(chat))
    },
  })
}
