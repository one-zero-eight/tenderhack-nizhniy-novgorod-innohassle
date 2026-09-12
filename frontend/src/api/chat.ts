import { eventsFetch } from '@/api'
import type { SchemaChatOut, SchemaChatPage, SchemaCloseIn, SchemaHandoffIn, SchemaHandoffOfferOut, SchemaMessagePage, SchemaRatingIn, SchemaRatingOut, SchemaSendResult } from '@/api/types'

/**
 * Backend chat endpoints, typed via the generated OpenAPI client.
 *
 * Every helper unwraps `{ data, error }` from openapi-fetch and throws a
 * normalized `Error` whose `message` is the backend's `detail.message` when
 * present. Errors are also tagged with `status` so TanStack Query's retry
 * policy (which skips 4xx) keeps working.
 */

/** Backend error body: `{"detail": {"code": "...", "message": "..."}}` or a 422 list. */
interface BackendErrorDetail {
  code?: string
  message?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string

  constructor(status: number, message: string, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

/** Turns an openapi-fetch error payload into a readable `ApiError`. */
function toApiError(error: unknown): ApiError {
  if (error && typeof error === 'object') {
    const { detail, status } = error as { detail?: BackendErrorDetail | unknown[]; status?: number }
    const httpStatus = typeof status === 'number' ? status : 0
    if (detail && !Array.isArray(detail) && typeof detail === 'object') {
      const { code, message } = detail
      if (message) return new ApiError(httpStatus, message, code)
    }
    if (Array.isArray(detail) && detail.length > 0) {
      // FastAPI 422 validation error list.
      return new ApiError(httpStatus, 'Проверьте корректность отправленных данных')
    }
  }
  return new ApiError(0, 'Не удалось выполнить запрос')
}

/** Throws a normalized error when openapi-fetch reported one. */
function unwrap<T>(data: T | undefined, error: unknown): T {
  if (error) throw toApiError(error)
  if (data === undefined) throw new ApiError(0, 'Пустой ответ сервера')
  return data
}

export async function fetchChats(params?: { status?: SchemaChatOut['status']; offset?: number; limit?: number }): Promise<SchemaChatPage> {
  const { data, error } = await eventsFetch.GET('/chats', {
    params: { query: { status: params?.status, offset: params?.offset, limit: params?.limit } },
  })
  return unwrap(data, error)
}

export async function fetchChat(chatId: string): Promise<SchemaChatOut> {
  const { data, error } = await eventsFetch.GET('/chats/{chat_id}', { params: { path: { chat_id: chatId } } })
  return unwrap(data, error)
}

export async function createChat(): Promise<SchemaChatOut> {
  const { data, error } = await eventsFetch.POST('/chats')
  return unwrap(data, error)
}

export async function fetchChatMessages(chatId: string, afterSequence = 0, limit = 50): Promise<SchemaMessagePage> {
  const { data, error } = await eventsFetch.GET('/chats/{chat_id}/messages', {
    params: { path: { chat_id: chatId }, query: { after_sequence: afterSequence, limit } },
  })
  return unwrap(data, error)
}

export async function sendChatMessage(chatId: string, text: string, clientMessageId: string): Promise<SchemaSendResult> {
  const { data, error } = await eventsFetch.POST('/chats/{chat_id}/messages', {
    params: { path: { chat_id: chatId } },
    body: { text, client_message_id: clientMessageId },
  })
  return unwrap(data, error)
}

export async function requestHandoffOffer(chatId: string): Promise<SchemaHandoffOfferOut> {
  const { data, error } = await eventsFetch.POST('/chats/{chat_id}/handoff-offer', {
    params: { path: { chat_id: chatId } },
  })
  return unwrap(data, error)
}

export async function handoffChat(chatId: string, body: SchemaHandoffIn = {}): Promise<SchemaChatOut> {
  const { data, error } = await eventsFetch.POST('/chats/{chat_id}/handoff', {
    params: { path: { chat_id: chatId } },
    body,
  })
  return unwrap(data, error)
}

export async function closeChat(chatId: string, body: SchemaCloseIn): Promise<SchemaChatOut> {
  const { data, error } = await eventsFetch.POST('/chats/{chat_id}/close', {
    params: { path: { chat_id: chatId } },
    body,
  })
  return unwrap(data, error)
}

export async function rateMessage(messageId: string, body: SchemaRatingIn): Promise<SchemaRatingOut> {
  const { data, error } = await eventsFetch.PUT('/messages/{message_id}/rating', {
    params: { path: { message_id: messageId } },
    body,
  })
  return unwrap(data, error)
}
