import { ChatStatus, SenderType, type SchemaActorOut, type SchemaChatOut, type SchemaMessageOut } from '@/api/types'

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
  /** Title provided by the backend (generated from the first message). */
  title: string
  status: ChatStatus
  recipient: ChatRecipientKind
  /** Human-readable recipient, e.g. recipient display name. */
  recipientLabel: string
  /** Support line name when bound to a line (queue or assigned operator). */
  lineName: string | null
  createdAt: string
  updatedAt: string
  closeReason: SchemaChatOut['close_reason']
  operator: SchemaActorOut | null
  /** Rating left on the chat, when the backend provides one. */
  rating: SchemaChatOut['rating']
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
  /** Set while tokens are still streaming into this message. */
  isStreaming?: boolean
  /**
   * Support line (`L1`–`L3`) when this message is a hand-off notice. Rendered
   * as a divider instead of a chat bubble.
   */
  redirectLine?: string | null
  /** Reason attached to a hand-off, when available. */
  redirectReason?: string | null
}

/**
 * Maps an API chat to the UI view model. The backend generates a `title` from
 * the first message, so no client-side derivation is needed.
 */
export function toChatView(chat: SchemaChatOut): ChatView {
  return {
    id: chat.id,
    title: chat.title || CHAT_TITLE_FALLBACK,
    status: chat.status,
    recipient: chat.recipient.kind,
    recipientLabel: chat.recipient.display_name,
    lineName: chat.support_line?.name ?? null,
    createdAt: chat.created_at,
    updatedAt: chat.updated_at,
    closeReason: chat.close_reason,
    operator: chat.operator,
    rating: chat.rating ?? null,
  }
}

/** Maps an API message to the UI view model. */
export function toMessageView(message: SchemaMessageOut): MessageView {
  // The model sometimes writes its `transfer_to_support(...)` call as plain
  // text; keep that tool syntax out of the rendered answer and surface it as a
  // hand-off notice instead.
  const leakedLine = extractTransferLine(message.text)
  return {
    id: message.id,
    chatId: message.chat_id,
    sequence: message.sequence,
    senderType: message.sender_type,
    senderName: message.sender_name,
    supportLineId: message.support_line_id ?? null,
    text: leakedLine ? redirectNotice(leakedLine) : stripToolSyntax(message.text),
    citations: message.citations ?? [],
    createdAt: message.created_at,
    isRedacted: message.is_redacted,
    replyToMessageId: message.reply_to_message_id ?? null,
    redirectLine: leakedLine,
  }
}

/** First user message text from a message list, used to derive a chat title. */
export function firstUserMessageText(messages: MessageView[]): string | undefined {
  return messages.find((message) => message.senderType === SenderType.user)?.text
}

/** Fallback label for a chat without a generated title. */
export const CHAT_TITLE_FALLBACK = 'Новый чат'

/** Russian labels for chat statuses. */
export const CHAT_STATUS_LABELS: Record<ChatStatus, string> = {
  [ChatStatus.ai]: 'Ассистент',
  [ChatStatus.waiting_operator]: 'Ожидает оператора',
  [ChatStatus.operator]: 'Оператор',
  [ChatStatus.closed]: 'Закрыто',
}

/** Tailwind classes for status badges. */
export const CHAT_STATUS_CLASSES: Record<ChatStatus, string> = {
  [ChatStatus.ai]: 'bg-pale-blue text-main-blue',
  [ChatStatus.waiting_operator]: 'bg-orange/10 text-orange',
  [ChatStatus.operator]: 'bg-orange/10 text-orange',
  [ChatStatus.closed]: 'bg-light-gray/40 text-gray',
}

/** Russian labels for message authors, keyed by sender type. */
export const SENDER_LABELS: Record<SenderType, string> = {
  [SenderType.user]: 'Вы',
  [SenderType.ai]: 'ИИ-ассистент',
  [SenderType.operator]: 'Оператор',
  [SenderType.support]: 'Поддержка',
  [SenderType.system]: 'Система',
}

/** Names of the three human support lines. */
export const SUPPORT_LINE_NAMES: Record<string, string> = {
  L1: 'Линия 1',
  L2: 'Линия 2',
  L3: 'Линия 3',
}

/**
 * Matches a leaked `transfer_to_support(...)` tool call in assistant text.
 *
 * The language model sometimes writes the call verbatim instead of only
 * invoking it, so the tool syntax ends up inside the answer.
 */
const TRANSFER_CALL_PATTERN = /transfer_to_support\s*\([^)]*\)/gi

/** Matches the `line='L1'` / `line="L2"` argument of a transfer call. */
const TRANSFER_LINE_PATTERN = /line\s*=\s*['"]?(L?\d)['"]?/i

/**
 * Removes leaked `transfer_to_support(...)` calls from text. Used to keep tool
 * syntax out of the rendered answer both while streaming and after a refetch.
 */
export function stripToolSyntax(text: string): string {
  return text.replace(TRANSFER_CALL_PATTERN, '').replace(/\n{3,}/g, '\n\n').trim()
}

/**
 * Extracts the support line (`L1`–`L3`) from a leaked transfer call, if any.
 */
export function extractTransferLine(text: string): string | null {
  const call = TRANSFER_CALL_PATTERN.exec(text)
  TRANSFER_CALL_PATTERN.lastIndex = 0
  if (!call) return null
  const line = TRANSFER_LINE_PATTERN.exec(call[0])?.[1]
  if (!line) return null
  const normalized = line.toUpperCase().startsWith('L') ? line.toUpperCase() : `L${line}`
  return SUPPORT_LINE_NAMES[normalized] ? normalized : null
}

/** Human-readable notice shown when a chat is handed to a support line. */
export function redirectNotice(line: string | null, reason?: string | null): string {
  const name = line ? (SUPPORT_LINE_NAMES[line] ?? line) : 'службу поддержки'
  const base = `Обращение переведено на ${name}. Ожидайте подключения оператора.`
  return reason ? `${base} Причина: ${reason}` : base
}
