import createQueryClient from '@/api/create-query-client.ts'
import createFetchClient from 'openapi-fetch'
import { clearAuth, getToken } from '@/lib/auth-storage'
import { emitUnauthorized } from '@/lib/auth-events'
import * as eventsTypes from './types.ts'

export type { eventsTypes }

export const eventsFetch = createFetchClient<eventsTypes.paths>({
  baseUrl: import.meta.env.VITE_API_URL ?? '/api',
})

eventsFetch.use({
  onRequest({ request }) {
    const token = getToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  onResponse({ request, response }) {
    // A failed login attempt is not a session expiry: keep the form usable and
    // let the mutation surface the error.
    if (response.status === 401 && !request.url.includes('/auth/login')) {
      clearAuth()
      emitUnauthorized()
    }
    return response
  },
})

export const $api = createQueryClient(eventsFetch, 'api')
