import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createHandRule, deleteHandRule, fetchHandRules, updateHandRule, type HandRuleInput, type HandRulePatch } from '@/lib/handrules-api'

export const handRulesQueryKey = ['handrules'] as const

/** Lists all hand-rules. */
export function useHandRules() {
  return useQuery({
    queryKey: handRulesQueryKey,
    queryFn: () => fetchHandRules(),
    staleTime: 1000 * 30,
  })
}

/** Creates a hand-rule and refreshes the list. */
export function useCreateHandRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: HandRuleInput) => createHandRule(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: handRulesQueryKey }),
  })
}

/** Updates a hand-rule and refreshes the list. */
export function useUpdateHandRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ ruleId, patch }: { ruleId: string; patch: HandRulePatch }) => updateHandRule(ruleId, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: handRulesQueryKey }),
  })
}

/** Deletes a hand-rule and refreshes the list. */
export function useDeleteHandRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ruleId: string) => deleteHandRule(ruleId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: handRulesQueryKey }),
  })
}
