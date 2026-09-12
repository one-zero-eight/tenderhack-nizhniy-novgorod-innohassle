import { useCallback, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { streamChatMessage, sendChatMessage } from '@/api/chat'
import { chatQueryKey } from '@/hooks/useChat'
import { chatsQueryKey } from '@/hooks/useChats'
import { SenderType } from '@/api/types'
import { extractTransferLine, redirectNotice, stripToolSyntax, toChatView, toMessageView, type MessageView } from '@/lib/chat-view'

export const chatMessagesQueryKey = (chatId: string) => ['chat', chatId, 'messages'] as const

/** Inserts or replaces a message in the cache, keeping the list ordered. */
function upsertMessage(prev: MessageView[] | undefined, message: MessageView): MessageView[] {
  const next = [...(prev ?? [])]
  const index = next.findIndex((item) => item.id === message.id)
  if (index === -1) next.push(message)
  else next[index] = message
  return next.sort((a, b) => a.sequence - b.sequence)
}

/** Maps a tool name to a short status string shown while it runs. */
function toolLabel(name: string, kwargs: Record<string, unknown>): string {
  const query = typeof kwargs.query === 'string' ? kwargs.query : typeof kwargs.q === 'string' ? kwargs.q : ''
  switch (name) {
    case 'search':
      return query ? `Ищу: ${query}` : 'Ищу в базе знаний…'
    case 'open':
      return 'Читаю раздел…'
    case 'sitemap':
      return 'Ищу ссылку на портале…'
    default:
      return `Выполняю: ${name}…`
  }
}

export interface StreamingState {
  /** Partial answer text while tokens are arriving. */
  text: string
  /** Human-readable description of the tool the assistant is running. */
  toolStatus: string | null
  isStreaming: boolean
}

const IDLE: StreamingState = { text: '', toolStatus: null, isStreaming: false }

/**
 * Sends a message and consumes the assistant's reply as a Server-Sent Events
 * stream, writing the partial answer into the messages cache as tokens arrive.
 *
 * Polling is intentionally not used: the stream is the source of truth while a
 * reply is in flight, and the caches are refreshed once at the end.
 */
export function useStreamMessage(chatId: string | undefined) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<StreamingState>(IDLE)
  const [error, setError] = useState<Error | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const cancel = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setState(IDLE)
  }, [])

  const send = useCallback(
    async (text: string) => {
      if (!chatId || !text.trim()) return
      setError(null)

      const key = chatMessagesQueryKey(chatId)
      const controller = new AbortController()
      abortRef.current = controller
      const clientMessageId = crypto.randomUUID()

      const now = new Date().toISOString()
      const maxSequence = (queryClient.getQueryData<MessageView[]>(key) ?? []).reduce(
        (max, message) => Math.max(max, message.sequence),
        0,
      )

      // Optimistic placeholders replaced by real ids via the `start`/`done`
      // events and the final cache refresh.
      const localUserId = `local-user-${crypto.randomUUID()}`
      let assistantId = `local-ai-${crypto.randomUUID()}`
      let content = ''
      let assistantStarted = false
      let completed = false
      // Number of events received; used to detect a stream that closed without
      // sending anything (e.g. the AI service is unreachable).
      let received = 0
      // Support line once the model hands the chat off to a human.
      let redirectLine: string | null = null
      let redirectReason: string | null = null

      const baseMessage: Omit<MessageView, 'id' | 'sequence' | 'senderType' | 'senderName'> = {
        chatId,
        supportLineId: null,
        text,
        citations: [],
        createdAt: now,
        isRedacted: false,
        replyToMessageId: null,
        rating: null,
      }

      queryClient.setQueryData<MessageView[]>(key, (prev) =>
        upsertMessage(prev, {
          ...baseMessage,
          id: localUserId,
          sequence: maxSequence + 1,
          senderType: SenderType.user,
          senderName: 'Вы',
        }),
      )

      const upsertAssistant = () => {
        // A redirect message is shown as a hand-off notice, never as raw tool
        // syntax or a stray partial answer.
        const text = redirectLine
          ? redirectNotice(redirectLine, redirectReason)
          : stripToolSyntax(content)
        queryClient.setQueryData<MessageView[]>(key, (prev) =>
          upsertMessage(prev, {
            ...baseMessage,
            id: assistantId,
            sequence: maxSequence + 2,
            senderType: SenderType.ai,
            senderName: 'ИИ-помощник',
            text,
            isStreaming: !redirectLine,
            redirectLine,
            redirectReason,
          }),
        )
      }

      setState({ text: '', toolStatus: null, isStreaming: true })

      try {
        for await (const event of streamChatMessage(chatId, text, clientMessageId, controller.signal)) {
          received += 1
          switch (event.type) {
            case 'start':
              assistantId = event.messageId || assistantId
              assistantStarted = true
              upsertAssistant()
              break
            case 'token':
              content = event.content
              // The model may leak its `transfer_to_support(...)` call as text;
              // detect it so the answer turns into a hand-off notice.
              if (!redirectLine) redirectLine = extractTransferLine(content)
              setState((prev) => ({ ...prev, text: stripToolSyntax(content) }))
              upsertAssistant()
              break
            case 'tool_call':
              setState((prev) => ({ ...prev, toolStatus: toolLabel(event.name, event.kwargs) }))
              break
            case 'tool_result':
              setState((prev) => ({ ...prev, toolStatus: null }))
              break
            case 'error':
              setError(new Error(event.message))
              break
            case 'done':
              content = event.content || content
              // Prefer the explicit redirect event, but fall back to a leaked
              // call in the final text.
              if (!redirectLine) redirectLine = extractTransferLine(content)
              completed = true
              if (!assistantStarted) {
                assistantId = event.messageId || assistantId
              }
              upsertAssistant()
              setState(IDLE)
              break
            case 'redirect':
              redirectLine = event.line || redirectLine
              redirectReason = event.reason ?? redirectReason
              setState((prev) => ({ ...prev, toolStatus: null }))
              upsertAssistant()
              break
          }
        }
      } catch (err) {
        if ((err as Error)?.name !== 'AbortError') setError(err as Error)
      } finally {
        const aborted = controller.signal.aborted
        if (received === 0 && !aborted) {
          // The stream closed without emitting a single event — the AI service
          // is likely unreachable. Fall back to the blocking JSON endpoint so
          // the user still gets a reply.
          try {
            const result = await sendChatMessage(chatId, text, clientMessageId)
            queryClient.setQueryData<MessageView[]>(key, (prev) => {
              // Drop optimistic placeholders; the server list is authoritative.
              let next = (prev ?? []).filter((message) => !message.id.startsWith('local-'))
              for (const message of result.messages) next = upsertMessage(next, toMessageView(message))
              return next
            })
            queryClient.setQueryData(chatQueryKey(chatId), toChatView(result.chat))
          } catch (fallbackError) {
            setError(fallbackError as Error)
          }
        } else if (!completed && !aborted) {
          // Events arrived but the stream ended before `done`.
          setError(new Error('Соединение прервано. Ответ мог прийти не полностью.'))
        }
        abortRef.current = null
        // Clear the streaming flag on the assistant bubble.
        queryClient.setQueryData<MessageView[]>(key, (prev) =>
          (prev ?? []).map((message) => (message.isStreaming ? { ...message, isStreaming: false } : message)),
        )
        setState(IDLE)
        // Reconcile with the server: real ids, sequences, status and title.
        queryClient.invalidateQueries({ queryKey: key })
        queryClient.invalidateQueries({ queryKey: chatQueryKey(chatId) })
        queryClient.invalidateQueries({ queryKey: chatsQueryKey })
      }
    },
    [chatId, queryClient],
  )

  return { send, cancel, error, ...state }
}
