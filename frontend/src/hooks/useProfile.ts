import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchProfile, updateUserRole } from '@/api/chat'
import type { SchemaProfileViewOut, Role } from '@/api/types'

export const profileQueryKey = ['profile'] as const

/** Loads the signed-in user's full profile (company, procurements, offers…). */
export function useProfile() {
  return useQuery<SchemaProfileViewOut, Error>({
    queryKey: profileQueryKey,
    queryFn: fetchProfile,
    staleTime: 1000 * 60 * 5,
  })
}

/** Switches the account between buyer and seller, refreshing the profile. */
export function useUpdateUserRole() {
  const queryClient = useQueryClient()
  return useMutation<SchemaProfileViewOut, Error, Role>({
    mutationFn: updateUserRole,
    onSuccess: (profile) => queryClient.setQueryData(profileQueryKey, profile),
  })
}
