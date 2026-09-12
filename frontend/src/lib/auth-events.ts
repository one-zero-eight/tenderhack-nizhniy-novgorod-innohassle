type Listener = () => void

const listeners = new Set<Listener>()

/**
 * Subscribes to "the API rejected our credentials (401)" events. The API client
 * emits this so the app can clear the session and redirect to the login page
 * without importing the router into the API layer.
 *
 * @returns an unsubscribe function.
 */
export function onUnauthorized(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function emitUnauthorized(): void {
  listeners.forEach((listener) => listener())
}
