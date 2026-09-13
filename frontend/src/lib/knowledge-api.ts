/**
 * Knowledge-base API client.
 *
 * These endpoints live on the API origin under `/ml-api/knowledge-base` and are
 * public (no auth). The OpenAPI spec does not describe their response bodies,
 * so the shapes below are hand-written from the actual payloads.
 */

const API_ORIGIN = import.meta.env.VITE_API_URL ?? '/api'
export { resolveAssetSrc as resolveKnowledgeSrc } from '@/lib/assets'

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
  /** Markdown body. Image paths are absolute (`/ml-assets/image/<slug>/…`). */
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

/** Word private-use bullets left over from PDF/DOCX conversion. */
const WORD_BULLET_RE = /[\uF0B7\uF0A7\u25AA\u25CF]\s*/g
/** HTML-escaped tags like `&lt;xsd:element …/&gt;` — not bare `&lt;` in encoding tables. */
const ESCAPED_TAG_RE = /&lt;(\/?[A-Za-z][^&]*?)&gt;/g
/**
 * Adds an image preview under a standalone `<picture>url</picture>` example
 * (a whole fenced block or a bare line). Leaves `<picture>` tags inside larger
 * XML listings untouched.
 */
function enhancePictureExamples(text: string): string {
  const lines = text.split('\n')
  const out: string[] = []
  let inFence = false

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? ''

    if (/^```/.test(line)) {
      if (!inFence) {
        const picture = lines[i + 1]?.match(/^<picture>(https?:\/\/[^<\s]+)<\/picture>\s*$/i)
        const closer = lines[i + 2]
        if (picture && closer && /^```/.test(closer)) {
          const url = picture[1]
          out.push('```', `<picture>${url}</picture>`, '```', '', `![Пример изображения товара](${url})`)
          i += 2
          continue
        }
        inFence = true
      } else {
        inFence = false
      }
      out.push(line)
      continue
    }

    if (!inFence) {
      const picture = line.match(/^<picture>(https?:\/\/[^<\s]+)<\/picture>\s*$/i)
      if (picture) {
        const url = picture[1]
        out.push('```', `<picture>${url}</picture>`, '```', '', `![Пример изображения товара](${url})`)
        continue
      }
    }

    out.push(line)
  }

  return out.join('\n')
}

/** True when a fence is collapsed XML that benefits from line breaks. */
function shouldPrettyPrintXml(code: string): boolean {
  const trimmed = code.trim()
  if (!trimmed.includes('<')) return false
  const tagCount = (trimmed.match(/</g) ?? []).length
  if (tagCount < 2) return false
  const lines = trimmed.split('\n').map((line) => line.trim()).filter(Boolean)
  // "1 <a> 2 <b> 3 <c>" — PDF jammed numbered lines into one.
  if (lines.length === 1 && /^\d+\s+</.test(trimmed) && /\s\d+\s+</.test(trimmed)) return true
  // Single (or nearly single) long line of tags.
  if (lines.length <= 2 && trimmed.length > 80) return true
  return false
}

/**
 * Splits jammed "1 <tag> 2 <tag>" listings into one numbered line each.
 */
function splitNumberedXmlLines(code: string): string {
  // Line numbers are " N " separators from the PDF; keep "..." placeholder lines too.
  return code.trim().replace(/\s+(?=\d+\s+)/g, '\n')
}

/**
 * Inserts newlines/indent between XML tags for collapsed one-liners.
 */
function prettyPrintXml(code: string): string {
  const tokens = code
    .trim()
    .replace(/>\s+</g, '>\n<')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

  const out: string[] = []
  let depth = 0
  for (const line of tokens) {
    const closing = /^<\//.test(line)
    const selfClosing = /\/>$/.test(line) || /^<\?/.test(line) || /^<!/.test(line)
    const openClose = /^<[^/?!][^>]*>[\s\S]*<\/[^>]+>$/.test(line)

    if (closing) depth = Math.max(0, depth - 1)
    out.push(`${'  '.repeat(depth)}${line}`)
    if (!closing && !selfClosing && !openClose && /^</.test(line)) depth += 1
  }
  return out.join('\n')
}

function formatXmlFenceBody(code: string): string {
  if (!shouldPrettyPrintXml(code)) return code
  const trimmed = code.trim()
  if (/^\d+\s+</.test(trimmed) && /\s\d+\s+</.test(trimmed)) {
    return splitNumberedXmlLines(trimmed)
  }
  return prettyPrintXml(trimmed)
}

/**
 * Pretty-prints collapsed XML inside markdown fences so examples are readable.
 */
function formatXmlCodeFences(text: string): string {
  return text.replace(/```([^\n]*)\n([\s\S]*?)```/g, (_match, info: string, body: string) => {
    return `\`\`\`${info}\n${formatXmlFenceBody(body)}\n\`\`\``
  })
}

/**
 * Normalizes manual markdown before render: Word bullets, escaped XML tags,
 * line-broken XML examples, and preview images for `<picture>` URLs.
 */
export function prepareManualMarkdown(content: string): string {
  let text = content.replace(WORD_BULLET_RE, '').replace(/\\_/g, '_')
  text = text.replace(ESCAPED_TAG_RE, (_, inner: string) => `<${inner}>`)
  text = text.replace(/^(\s*[-*+]\s)\s+/gm, '$1')
  text = formatXmlCodeFences(text)
  return enhancePictureExamples(text)
}
