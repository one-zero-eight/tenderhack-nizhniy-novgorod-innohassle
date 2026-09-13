import { useMemo } from 'react'
import { useProfile } from '@/hooks/useProfile'
import type { SchemaContractOut } from '@/api/types'

/**
 * Contracts available to the signed-in user.
 *
 * There is no dedicated contracts list endpoint, so they are read from the
 * profile response (`GET /profile` → `contracts`).
 */
export function useContracts() {
  const query = useProfile()
  const contracts = useMemo<SchemaContractOut[]>(() => query.data?.contracts ?? [], [query.data])
  return { ...query, contracts }
}
