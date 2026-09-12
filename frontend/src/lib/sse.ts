/**
 * Minimal Server-Sent Events client over `fetch`.
 *
 * The native `EventSource` cannot send a POST body or an Authorization header,
 * so the stream is consumed manually from the response body.
 */

export interface SseEvent {
  /** Event name; defaults to `message` when the server omits it. */
  event: string
  /** Raw `data:` payload, joined across multiple data lines. */
  data: string
}

/**
 * Parses a `text/event-stream` body, invoking `onEvent` for every complete
 * event. Resolves when the stream ends.
 */
async function readSse(response: Response, onEvent: (event: SseEvent) => void, signal?: AbortSignal): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('Поток недоступен')

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      if (signal?.aborted) break
      let chunk: ReadableStreamReadResult<Uint8Array>
      try {
        chunk = await reader.read()
      } catch {
        // The server can close the socket abruptly (no graceful EOF). Treat it
        // as the end of the stream: a `done` event is what marks completion.
        break
      }
      const { done, value } = chunk
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // Events are separated by a blank line.
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const rawEvent = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const parsed = parseEvent(rawEvent)
        if (parsed) onEvent(parsed)
        boundary = buffer.indexOf('\n\n')
      }
    }
  } finally {
    reader.cancel().catch(() => {})
  }
}

/** Parses a single raw SSE block (`event:`/`data:` lines) into an event. */
function parseEvent(block: string): SseEvent | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of block.split('\n')) {
    if (line.startsWith(':')) continue // comment / keep-alive
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
  }

  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

/**
 * Performs a streaming POST and yields parsed SSE events until the stream ends.
 * Throws with the backend's error message when the response is not OK.
 */
export async function* postSse(url: string, init: RequestInit & { signal?: AbortSignal }): AsyncGenerator<SseEvent> {
  const response = await fetch(url, {
    ...init,
    headers: { ...init.headers, Accept: 'text/event-stream' },
  })

  if (!response.ok) {
    let message = 'Не удалось отправить сообщение'
    try {
      const body = await response.json()
      const detail = body?.detail
      if (typeof detail === 'string') message = detail
      else if (detail && typeof detail === 'object' && typeof detail.message === 'string') message = detail.message
    } catch {
      // Non-JSON error body; keep the default message.
    }
    throw new Error(message)
  }

  // Collect events and re-yield them; the parser is callback-based.
  const queue: SseEvent[] = []
  let resolveNext: (() => void) | null = null
  let finished = false
  let failure: unknown = null

  const notify = () => {
    resolveNext?.()
    resolveNext = null
  }

  const done = readSse(response, (event) => {
    queue.push(event)
    notify()
  }, init.signal)
    .catch((error) => {
      failure = error
    })
    .finally(() => {
      finished = true
      notify()
    })

  while (!finished || queue.length > 0) {
    if (queue.length === 0) {
      await new Promise<void>((resolve) => {
        resolveNext = resolve
      })
      continue
    }
    yield queue.shift() as SseEvent
  }

  await done
  if (failure) throw failure
}
