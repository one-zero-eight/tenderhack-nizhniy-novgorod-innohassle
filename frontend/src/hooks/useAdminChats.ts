import { useQuery } from '@tanstack/react-query'
import { fetchAdminChats, type AdminChatFilters } from '@/api/chat'

/** Query key for the admin chat history, including the active filters. */
export const adminChatsQueryKey = (filters: AdminChatFilters) => ['admin', 'chats', filters] as const

/**
 * Loads every chat in the system for the admin history view.
 * Server-side paginated through `offset`/`limit`.
 */
export function useAdminChats(filters: AdminChatFilters) {
  return useQuery({
    queryKey: adminChatsQueryKey(filters),
    queryFn: () => fetchAdminChats(filters),
    placeholderData: (previous) => previous,
  })
}
