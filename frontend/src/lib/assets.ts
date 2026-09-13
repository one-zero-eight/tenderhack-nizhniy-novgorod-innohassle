/**
 * Helpers for ML-service asset paths.
 *
 * Manual and chat content link images as `/ml-assets/image/<slug>/<file>`. Those
 * paths are absolute on the API origin, so they need rewriting before use in the
 * browser (which would otherwise resolve them against the frontend origin).
 */

export const API_ORIGIN = import.meta.env.VITE_API_URL ?? '/api'

/**
 * Rewrites an asset path from the ML service so it resolves against the backend
 * origin. Non-asset or already-absolute URLs are returned unchanged.
 */
export function resolveAssetSrc(src: string): string {
  if (!src) return src
  if (src.startsWith('/ml-assets/')) return `${API_ORIGIN}${src}`
  return src
}
