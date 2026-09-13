/**
 * Helpers for API-served assets.
 *
 * Manual content links images as `/ml-assets/image/<slug>/<file>` and chat
 * attachments as `/attachments/<file_id>`. Both are absolute on the API origin,
 * so they need rewriting before use in the browser (which would otherwise
 * resolve them against the frontend origin).
 */

export const API_ORIGIN = import.meta.env.VITE_API_URL ?? '/api'

/** Root-relative paths served by the API rather than the frontend. */
const API_PATH_PREFIXES = ['/ml-assets/', '/attachments/']

/**
 * Rewrites a root-relative API path so it resolves against the backend origin.
 * Absolute URLs (http/https/data/blob) and unrelated paths are returned as-is.
 */
export function resolveAssetSrc(src: string): string {
  if (!src) return src
  if (API_PATH_PREFIXES.some((prefix) => src.startsWith(prefix))) {
    return `${API_ORIGIN}${src}`
  }
  return src
}
