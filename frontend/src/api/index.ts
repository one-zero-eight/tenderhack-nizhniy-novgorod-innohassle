import createQueryClient from '@/api/create-query-client.ts'
import createFetchClient from 'openapi-fetch'
import * as eventsTypes from './types.ts'

export type { eventsTypes }

export const eventsFetch = createFetchClient<eventsTypes.paths>({
  baseUrl: import.meta.env.VITE_API_URL ?? '/api',
})
export const $api = createQueryClient(eventsFetch, 'api')
