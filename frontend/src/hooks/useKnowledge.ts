import { useQuery } from '@tanstack/react-query'
import { fetchManuals, fetchManualStructure, fetchSection } from '@/lib/knowledge-api'

export const manualsQueryKey = ['knowledge', 'manuals'] as const
export const manualStructureQueryKey = (slug: string) => ['knowledge', 'manual', slug] as const
export const sectionQueryKey = (slug: string, sectionId: string) => ['knowledge', 'manual', slug, sectionId] as const

/** Lists all manuals. */
export function useManuals() {
  return useQuery({
    queryKey: manualsQueryKey,
    queryFn: fetchManuals,
    staleTime: 1000 * 60 * 10,
  })
}

/** Loads a manual's outline, used for the sidebar table of contents. */
export function useManualStructure(slug: string | undefined) {
  return useQuery({
    queryKey: manualStructureQueryKey(slug ?? ''),
    queryFn: () => fetchManualStructure(slug as string),
    enabled: !!slug,
    staleTime: 1000 * 60 * 10,
  })
}

/** Loads a single section's content. */
export function useSection(slug: string | undefined, sectionId: string | undefined) {
  return useQuery({
    queryKey: sectionQueryKey(slug ?? '', sectionId ?? ''),
    queryFn: () => fetchSection(slug as string, sectionId as string),
    enabled: !!slug && !!sectionId,
    staleTime: 1000 * 60 * 10,
  })
}
