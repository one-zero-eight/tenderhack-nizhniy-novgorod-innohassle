import { eventsFetch } from '@/api'
import type { SchemaChatFileOut, SchemaChatOut, SchemaChatPage, SchemaContractOut, SchemaMessagePage, SchemaProfileViewOut, SchemaRatingIn, SchemaRatingOut, SchemaSendResult, Role } from '@/api/types'
import { getToken } from '@/lib/auth-storage'
import { resolveAssetSrc } from '@/lib/assets'
import { postSse } from '@/lib/sse'

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

/** Filters accepted by the admin chat history endpoint. */
export interface AdminChatFilters {
  from?: string | null
  to?: string | null
  status?: SchemaChatOut['status'] | null
  line_id?: number | null
  operator_id?: string | null
  topic?: string | null
  subtopic?: string | null
  /** Only chats rated this many stars or fewer (unrated chats are excluded). */
  rating_lte?: number | null
  /** Only chats rated this many stars or more. */
  rating_gte?: number | null
  offset?: number
  limit?: number
}

/**
 * Lists every chat in the system (admin only) for the history view.
 * Newest first; paginated via `offset`/`limit`.
 */
export async function fetchAdminChats(filters: AdminChatFilters = {}): Promise<SchemaChatPage> {
  const { data, error } = await eventsFetch.GET('/admin/chats', {
    params: {
      query: {
        from: filters.from ?? undefined,
        to: filters.to ?? undefined,
        status: filters.status ?? undefined,
        line_id: filters.line_id ?? undefined,
        operator_id: filters.operator_id ?? undefined,
        topic: filters.topic ?? undefined,
        subtopic: filters.subtopic ?? undefined,
        rating_lte: filters.rating_lte ?? undefined,
        rating_gte: filters.rating_gte ?? undefined,
        offset: filters.offset,
        limit: filters.limit,
      },
    },
  })
  return unwrap(data, error)
}

/** Page size used when pulling every chat for aggregation. */
const ALL_CHATS_PAGE_SIZE = 100

/**
 * Maximum star rating that still counts as a problem worth analysing on the
 * issues page. Higher-rated chats are considered resolved well enough.
 */
export const ISSUES_MAX_RATING = 3

/**
 * Fetches every poorly-rated chat (≤ {@link ISSUES_MAX_RATING} stars), following
 * pagination until all pages are read.
 *
 * Used by the issues view: only dissatisfied users reveal recurring problems,
 * and chats without a rating are excluded by the backend filter.
 */
export async function fetchAllAdminChats(): Promise<SchemaChatOut[]> {
  const all: SchemaChatOut[] = []
  let offset = 0
  // Guard against an unbounded loop if the backend misbehaves.
  for (let page = 0; page < 100; page += 1) {
    const result = await fetchAdminChats({ offset, limit: ALL_CHATS_PAGE_SIZE, rating_lte: ISSUES_MAX_RATING })
    all.push(...result.items)
    offset += result.items.length
    if (result.items.length === 0 || offset >= result.total) break
  }
  return all
}

export async function createChat(): Promise<SchemaChatOut> {
  const { data, error } = await eventsFetch.POST('/chats', { body: {} as never })
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

/** Rates the conversation via `PUT /chats/{chat_id}/rating`. */
export async function rateChat(chatId: string, body: SchemaRatingIn): Promise<SchemaRatingOut> {
  const { data, error } = await eventsFetch.PUT('/chats/{chat_id}/rating', {
    params: { path: { chat_id: chatId } },
    body,
  })
  return unwrap(data, error)
}

/* ----------------------------------------------------------------- chat files */

/**
 * Uploads a file to a chat via `POST /chats/{chat_id}/upload`.
 *
 * Uploaded files stay pending until the next message is sent: the AI service
 * attaches them to that turn, so callers upload first and then send the text.
 */
export async function uploadChatFile(chatId: string, file: File): Promise<SchemaChatFileOut> {
  const token = getToken()
  const body = new FormData()
  body.append('file', file, file.name)

  const baseUrl = import.meta.env.VITE_API_URL ?? '/api'
  const response = await fetch(`${baseUrl}/chats/${encodeURIComponent(chatId)}/upload`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body,
  })

  if (!response.ok) {
    let message = 'Не удалось загрузить файл'
    try {
      const payload = await response.json()
      const detail = payload?.detail
      if (typeof detail === 'string') message = detail
      else if (detail && typeof detail.message === 'string') message = detail.message
    } catch {
      // Non-JSON error body.
    }
    throw new ApiError(response.status, message)
  }

  return (await response.json()) as SchemaChatFileOut
}

/** Lists the pending files uploaded to a chat. */
export async function fetchChatFiles(chatId: string): Promise<SchemaChatFileOut[]> {
  const { data, error } = await eventsFetch.GET('/chats/{chat_id}/files', {
    params: { path: { chat_id: chatId } },
  })
  return unwrap(data, error)
}

/** Removes a pending file from a chat. */
export async function deleteChatFile(chatId: string, fileId: string): Promise<void> {
  const { error } = await eventsFetch.DELETE('/chats/{chat_id}/files/{file_id}', {
    params: { path: { chat_id: chatId, file_id: fileId } },
  })
  if (error) throw toApiError(error)
}

/** Absolute URL for a chat file, resolved against the API origin. */
export function chatFileUrl(file: SchemaChatFileOut): string {
  return resolveAssetSrc(file.url)
}

/* -------------------------------------------------------------------- profile */

/** Full profile of the signed-in user: company, procurements, offers, contracts. */
export async function fetchProfile(): Promise<SchemaProfileViewOut> {
  const { data, error } = await eventsFetch.GET('/profile')
  return unwrap(data, error)
}

/** Loads a single contract by id (`GET /profile/contracts/{contract_id}`). */
export async function fetchContract(contractId: string): Promise<SchemaContractOut> {
  const { data, error } = await eventsFetch.GET('/profile/contracts/{contract_id}', {
    params: { path: { contract_id: contractId } },
  })
  return unwrap(data, error)
}

/** Switches the account between buyer and seller via `PATCH /profile/role`. */
export async function updateUserRole(role: Role): Promise<SchemaProfileViewOut> {
  const { data, error } = await eventsFetch.PATCH('/profile/role', { body: { role } })
  return unwrap(data, error)
}

/* ------------------------------------------------------------------ streaming */

/**
 * Events emitted by the backend's SSE stream while answering a message.
 *
 * - `start`       — an AI message id has been allocated.
 * - `token`       — a chunk of the answer; `content` is the full text so far.
 * - `tool_call`   — the assistant invoked a tool (search, open, …).
 * - `tool_result` — a tool finished.
 * - `redirect`    — the chat was handed off to a support line.
 * - `error`       — a non-fatal error (e.g. moderation blocked the message).
 * - `done`        — the final, complete answer.
 */
export type ChatStreamEvent =
  | { type: 'start'; messageId: string }
  | { type: 'token'; content: string }
  | { type: 'tool_call'; id: string; name: string; kwargs: Record<string, unknown>; phase: 'start' }
  | { type: 'tool_result'; id: string; name: string; output: string; error: boolean; phase: 'end' }
  | { type: 'redirect'; line: string; reason: string | null }
  | { type: 'error'; message: string }
  | { type: 'done'; messageId: string; content: string }

/** Parses a raw SSE frame into a typed stream event, or `null` if unknown. */
function parseStreamEvent(event: string, raw: string): ChatStreamEvent | null {
  let data: Record<string, unknown>
  try {
    data = JSON.parse(raw) as Record<string, unknown>
  } catch {
    data = { content: raw }
  }
  const str = (value: unknown): string => (typeof value === 'string' ? value : '')

  switch (event) {
    case 'start':
      return { type: 'start', messageId: str(data.message_id) }
    case 'token':
      return { type: 'token', content: str(data.content) }
    case 'tool_call':
      return {
        type: 'tool_call',
        id: str(data.id),
        name: str(data.name),
        kwargs: (data.kwargs as Record<string, unknown>) ?? {},
        phase: 'start',
      }
    case 'tool_result':
      return {
        type: 'tool_result',
        id: str(data.id),
        name: str(data.name),
        output: str(data.output),
        error: data.error === true,
        phase: 'end',
      }
    case 'redirect':
      return { type: 'redirect', line: str(data.line), reason: data.reason ? str(data.reason) : null }
    case 'error':
      return { type: 'error', message: str(data.message) || 'Ошибка сервера' }
    case 'done':
      return { type: 'done', messageId: str(data.message_id), content: str(data.content) }
    default:
      return null
  }
}

/**
 * Streams an assistant reply from `POST /chats/{chat_id}/stream`.
 *
 * Yields typed events as they arrive. Cancelling the generator (via the
 * provided `AbortSignal`) closes the connection, which the backend treats as a
 * client disconnect and stops work.
 */
export async function* streamChatMessage(
  chatId: string,
  text: string,
  clientMessageId: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const baseUrl = import.meta.env.VITE_API_URL ?? '/api'
  const token = getToken()

  const stream = postSse(`${baseUrl}/chats/${encodeURIComponent(chatId)}/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ text, client_message_id: clientMessageId }),
    signal,
  })

  for await (const sse of stream) {
    const parsed = parseStreamEvent(sse.event, sse.data)
    if (parsed) yield parsed
  }
}
