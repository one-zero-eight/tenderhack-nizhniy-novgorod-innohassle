/**
 * Domain models for the support chat feature.
 *
 * These mirror the backend OpenAPI schemas (see `backend/src/schemas/chat.py`).
 * Fields are named with the `chat_` prefix for the list projection used by the UI.
 */

export type ChatStatus = 'ai' | 'first-lane' | 'second-lane' | 'third-lane' | 'banned' | 'closed'

/**
 * Who authored a message. `first-lane` / `second-lane` / `third-lane` are
 * operators on support lines 1/2/3 (`Линия 1/2/3` in the backend).
 */
export type ChatMessageSender = 'user' | 'ai' | 'first-lane' | 'second-lane' | 'third-lane'

/**
 * A single message in a chat.
 */
export interface ChatMessageData {
  chatId: string
  id: number
  sender: ChatMessageSender
  text: string
  /** ISO 8601 timestamp, e.g. `2026-09-11T18:53:00+00:00`. */
  sent_at: string
  /**
   * True on the special AI message that hands the conversation off to a
   * support lane. Rendered as a delimiter, not a regular bubble. All other
   * messages (including lane replies) are `false`.
   */
  questionRedirected: boolean
}

/**
 * Lightweight chat representation for the chats list.
 */
export interface ChatMinimal {
  chat_id: string
  chat_title: string
  chat_status: ChatStatus
  /** ISO 8601 timestamp, e.g. `2026-09-11T18:53:00+00:00`. */
  chat_creation_date: string
}
