import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createChat, fetchChat } from '@/api/chat'
import { chatsQueryKey } from '@/hooks/useChats'
import { toChatView, type ChatView } from '@/lib/chat-view'

export const chatQueryKey = (chatId: string) => ['chat', chatId] as const

/**
 * Loads a single chat from `GET /chats/{id}`.
 *
 * Not polled: status changes are driven by the SSE stream while a reply is in
 * flight, and the query is invalidated when the stream settles.
 */
export function useChat(chatId: string | undefined) {
  return useQuery<ChatView, Error>({
    queryKey: chatQueryKey(chatId ?? ''),
    queryFn: async () => toChatView(await fetchChat(chatId as string)),
    enabled: !!chatId,
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
