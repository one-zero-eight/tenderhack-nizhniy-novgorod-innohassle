import { useQuery } from '@tanstack/react-query'
import { fetchAdminChats, fetchAllAdminChats, type AdminChatFilters } from '@/api/chat'

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

/**
 * Loads the full set of chats (every page), for aggregations such as grouping
 * by topic on the issues page.
 */
export function useAllAdminChats() {
  return useQuery({
    queryKey: ['admin', 'chats', 'all'] as const,
    queryFn: fetchAllAdminChats,
    staleTime: 1000 * 60,
  })
}
