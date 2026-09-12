import { ChatStatus, SenderType, type SchemaActorOut, type SchemaChatOut, type SchemaMessageOut, type SchemaSupportLineOut } from '@/api/types'

/**
 * View models for the support chat UI.
 *
 * The backend contract (`ChatOut` / `MessageOut`) is richer and uses different
 * naming than the UI needs, and it has no chat title. This module is the single
 * place that translates API payloads into the shapes the components render, so
 * components never depend on backend field names directly.
 */

/** What the recipient of a chat currently is. */
export type ChatRecipientKind = SchemaChatOut['recipient']['kind']

export interface ChatView {
  id: string
  /** Derived title: the first user message, or a fallback. */
  title: string
  status: ChatStatus
  recipient: ChatRecipientKind
  /** Human-readable recipient, e.g. recipient display name. */
  recipientLabel: string
  /** Support line name when bound to a line (queue or assigned operator). */
  lineName: string | null
  createdAt: string
  updatedAt: string
  /** True while the assistant is still generating a reply. */
  aiPending: boolean
  /** Suggested line the assistant recommends handing off to, if any. */
  suggestedLine: SchemaSupportLineOut | null
  closeReason: SchemaChatOut['close_reason']
  operator: SchemaActorOut | null
}

export interface MessageView {
  id: string
  chatId: string
  sequence: number
  senderType: SenderType
  /** Display name of the author, provided by the backend. */
  senderName: string
  /** Support line the author belongs to, if any. */
  supportLineId: number | null
  text: string
  citations: Record<string, unknown>[]
  createdAt: string
  isRedacted: boolean
  replyToMessageId: string | null
  rating: SchemaMessageOut['rating']
}

const CHAT_TITLE_FALLBACK = 'Обращение в поддержку'

/**
 * Derives a chat title. The backend stores no title, so the first user message
 * is used as the summary; when it is missing we fall back to a generic label.
 */
function deriveTitle(firstUserMessageText: string | undefined): string {
  const trimmed = firstUserMessageText?.trim()
  if (!trimmed) return CHAT_TITLE_FALLBACK
  return trimmed.length > 80 ? `${trimmed.slice(0, 80)}…` : trimmed
}

/** Maps an API chat to the UI view model. */
export function toChatView(chat: SchemaChatOut, firstUserMessageText?: string): ChatView {
  return {
    id: chat.id,
    title: deriveTitle(firstUserMessageText),
    status: chat.status,
    recipient: chat.recipient.kind,
    recipientLabel: chat.recipient.display_name,
    lineName: chat.support_line?.name ?? chat.suggested_line?.name ?? null,
    createdAt: chat.created_at,
    updatedAt: chat.updated_at,
    aiPending: chat.ai_pending,
    suggestedLine: chat.suggested_line,
    closeReason: chat.close_reason,
    operator: chat.operator,
  }
}

/** Maps an API message to the UI view model. */
export function toMessageView(message: SchemaMessageOut): MessageView {
  return {
    id: message.id,
    chatId: message.chat_id,
    sequence: message.sequence,
    senderType: message.sender_type,
    senderName: message.sender_name,
    supportLineId: message.support_line_id,
    text: message.text,
    citations: message.citations,
    createdAt: message.created_at,
    isRedacted: message.is_redacted,
    replyToMessageId: message.reply_to_message_id,
    rating: message.rating ?? null,
  }
}

/** First user message text from a message list, used to derive a chat title. */
export function firstUserMessageText(messages: MessageView[]): string | undefined {
  return messages.find((message) => message.senderType === SenderType.user)?.text
}

/** Russian labels for chat statuses. */
export const CHAT_STATUS_LABELS: Record<ChatStatus, string> = {
  [ChatStatus.ai]: 'Ассистент',
  [ChatStatus.handoff_offered]: 'Предложен перевод',
  [ChatStatus.waiting_operator]: 'Ожидает оператора',
  [ChatStatus.operator]: 'Оператор',
  [ChatStatus.closed]: 'Закрыто',
}

/** Tailwind classes for status badges. */
export const CHAT_STATUS_CLASSES: Record<ChatStatus, string> = {
  [ChatStatus.ai]: 'bg-pale-blue text-main-blue',
  [ChatStatus.handoff_offered]: 'bg-orange/10 text-orange',
  [ChatStatus.waiting_operator]: 'bg-orange/10 text-orange',
  [ChatStatus.operator]: 'bg-orange/10 text-orange',
  [ChatStatus.closed]: 'bg-light-gray/40 text-gray',
}

/** Russian labels for message authors, keyed by sender type. */
export const SENDER_LABELS: Record<SenderType, string> = {
  [SenderType.user]: 'Вы',
  [SenderType.ai]: 'ИИ-ассистент',
  [SenderType.operator]: 'Оператор',
  [SenderType.system]: 'Система',
}
