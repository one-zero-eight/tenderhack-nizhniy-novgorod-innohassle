/**
 * Knowledge-base API client.
 *
 * These endpoints live on the API origin under `/ml-api/knowledge-base` and are
 * public (no auth). The OpenAPI spec does not describe their response bodies,
 * so the shapes below are hand-written from the actual payloads.
 */

const API_ORIGIN = import.meta.env.VITE_API_URL ?? '/api'

/** Base for the knowledge-base endpoints, independent of the `/api` prefix. */
const KNOWLEDGE_BASE = `${API_ORIGIN}/ml-api/knowledge-base`

/** A manual as listed on the knowledge-base index. */
export interface ManualSummary {
  slug: string
  title: string
  /** Number of sections in the manual. */
  sections: number
  /** Frontend path, e.g. `/knowledge-base/{slug}`. */
  url: string
}

/** One entry in a manual's outline (table of contents). */
export interface ManualSection {
  id: string
  title: string
  /** Title prefixed with the section number, e.g. `2.1 Назначение…`. */
  title_line: string
  /** Nesting level, 0-based. */
  depth: number
  /** Ids of ancestor sections. */
  ancestors: string[]
  /** Whether this section has body content of its own. */
  has_content: boolean
  /** Ids of direct child sections. */
  children: string[]
  url: string
}

/** A manual outline. */
export interface ManualStructure {
  slug: string
  title: string
  sections: ManualSection[]
}

/** The body and navigation context of a single section. */
export interface SectionContent {
  slug: string
  manual_title: string
  id: string
  title: string
  title_line: string
  ancestors: string[]
  /** Ancestor titles ending with this section's title. */
  breadcrumbs: string[]
  children: string[]
  /** Plain text; paragraphs are separated by blank lines. */
  content: string
  url: string
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new Error(response.status === 404 ? 'Раздел не найден' : 'Не удалось загрузить данные')
  }
  return (await response.json()) as T
}

/** Lists all manuals. */
export function fetchManuals(): Promise<ManualSummary[]> {
  return getJson<ManualSummary[]>(KNOWLEDGE_BASE)
}

/** Loads a manual's outline by slug. */
export function fetchManualStructure(slug: string): Promise<ManualStructure> {
  return getJson<ManualStructure>(`${KNOWLEDGE_BASE}/${encodeURIComponent(slug)}`)
}

/** Loads a single section's content. */
export function fetchSection(slug: string, sectionId: string): Promise<SectionContent> {
  return getJson<SectionContent>(`${KNOWLEDGE_BASE}/${encodeURIComponent(slug)}/${encodeURIComponent(sectionId)}`)
}

/** Absolute URL for an image referenced by manual content. */
export function knowledgeAssetUrl(slug: string, filename: string): string {
  return `${API_ORIGIN}/ml-assets/image/${encodeURIComponent(slug)}/${encodeURIComponent(filename)}`
}
