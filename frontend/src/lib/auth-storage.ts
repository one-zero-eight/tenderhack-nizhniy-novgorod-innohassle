import type { SchemaTokenOut, SchemaUserOut } from '@/api/types'

const AUTH_KEY = 'support.auth'

export interface StoredAuth {
  accessToken: string
  /** Epoch milliseconds at which the access token expires, or `null` if unknown. */
  expiresAt: number | null
  user: SchemaUserOut | null
}

/**
 * Reads the persisted auth state. Returns `null` when nothing is stored or the
 * payload is malformed.
 */
function readAuth(): StoredAuth | null {
  const raw = localStorage.getItem(AUTH_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<StoredAuth>
    if (!parsed || typeof parsed.accessToken !== 'string') return null
    return {
      accessToken: parsed.accessToken,
      expiresAt: typeof parsed.expiresAt === 'number' ? parsed.expiresAt : null,
      user: parsed.user ?? null,
    }
  } catch {
    return null
  }
}

function writeAuth(auth: StoredAuth): void {
  localStorage.setItem(AUTH_KEY, JSON.stringify(auth))
}

function toExpiresAt(token: SchemaTokenOut): number | null {
  return token.expires_in ? Date.now() + token.expires_in * 1000 : null
}

/**
 * Returns the access token, or `null` when it is missing or has expired.
 * Expired tokens are treated as logged out since the backend offers no refresh.
 */
export function getToken(): string | null {
  const auth = readAuth()
  if (!auth) return null
  if (auth.expiresAt !== null && auth.expiresAt <= Date.now()) return null
  return auth.accessToken
}

/** Returns the cached user profile, if any. */
export function getStoredUser(): SchemaUserOut | null {
  return readAuth()?.user ?? null
}

export function isAuthenticated(): boolean {
  return getToken() !== null
}

/** Persists the access token returned by `POST /auth/login`. */
export function setToken(token: SchemaTokenOut): void {
  writeAuth({
    accessToken: token.access_token,
    expiresAt: toExpiresAt(token),
    user: readAuth()?.user ?? null,
  })
}

/** Persists the current user returned by `GET /auth/me`. */
export function setUser(user: SchemaUserOut): void {
  const auth = readAuth()
  if (!auth) return
  writeAuth({ ...auth, user })
}

export function setAuth(token: SchemaTokenOut, user: SchemaUserOut): void {
  writeAuth({ accessToken: token.access_token, expiresAt: toExpiresAt(token), user })
}

/** Removes all persisted auth state. */
export function clearAuth(): void {
  localStorage.removeItem(AUTH_KEY)
}
