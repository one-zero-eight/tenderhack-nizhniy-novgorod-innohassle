import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createChat, fetchChat } from '@/api/chat'
import { chatsQueryKey } from '@/hooks/useChats'
import { toChatView, type ChatView } from '@/lib/chat-view'

export const chatQueryKey = (chatId: string) => ['chat', chatId] as const

/**
 * Loads a single chat from `GET /chats/{id}`.
 *
 * Polls every 2s while the assistant is working so status changes (handoff
 * offer, operator assignment, closure) show up without a manual refresh.
 */
export function useChat(chatId: string | undefined) {
  return useQuery<ChatView, Error>({
    queryKey: chatQueryKey(chatId ?? ''),
    queryFn: async () => toChatView(await fetchChat(chatId as string)),
    enabled: !!chatId,
    refetchInterval: (query) => {
      const chat = query.state.data
      if (!chat) return 2000
      return chat.status === 'closed' ? false : 2000
    },
  })
}

/**
 * Creates a new chat via `POST /chats` and refreshes the chats list.
 */
export function useCreateChat() {
  const queryClient = useQueryClient()
  return useMutation<ChatView, Error, void>({
    mutationFn: async () => toChatView(await createChat()),
    onSuccess: (chat) => {
      queryClient.setQueryData(chatsQueryKey, (prev: ChatView[] | undefined) => (prev ? [chat, ...prev] : [chat]))
      queryClient.invalidateQueries({ queryKey: chatsQueryKey })
    },
  })
}
