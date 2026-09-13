import type { SchemaChatOut } from '@/api/types'

/**
 * Column layout shared by the chat row header and every row, so the columns
 * line up like a table while the rows still read as a list.
 */
export const CHAT_ROW_GRID = 'grid grid-cols-[minmax(0,1fr)_12rem_7rem_12rem_10rem] items-center gap-4 px-4'

/** Display name for the chat owner, falling back to the id. */
export function chatUserName(chat: SchemaChatOut): string {
  return chat.user_display_name || chat.user?.display_name || chat.display_name || chat.user_id
}
