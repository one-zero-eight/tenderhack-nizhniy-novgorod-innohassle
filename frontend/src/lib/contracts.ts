import type { SchemaChatOut, SchemaContractOut } from '@/api/types'

/**
 * Inline references inside a message, typed with `@`:
 *
 *   [[contract:cntr-1]]        → rendered as a contract chip
 *   @[Название обращения]      → rendered as a chat chip
 *
 * Contracts also carry a header line for the backend; chat references are sent
 * as the literal `@[name]` text with nothing else added.
 */

/** Marker wrapped around a contract id inside the message body. */
export const CONTRACT_MARKER_START = '[[contract:'
export const CONTRACT_MARKER_END = ']]'

/** Prefix used for the machine-readable contract header line. */
export const CONTRACT_PREFIX = 'Пользователь выбрал контракт: '

/** Matches the `Пользователь выбрал контракт: <id>` header line. */
const CONTRACT_PREFIX_LINE = /^Пользователь выбрал контракт:\s*(.+)$/gm

/** Matches an `@[Chat name]` chat reference. */
const CHAT_REFERENCE = /@\[([^\]]+)\]/g

/** Builds the inline token for a contract id. */
export function contractToken(contractId: string): string {
  return `${CONTRACT_MARKER_START}${contractId}${CONTRACT_MARKER_END}`
}

/** Builds the inline reference for a chat, e.g. `@[Не приходит счёт]`. */
export function chatToken(chatName: string): string {
  return `@[${chatName}]`
}

/** Builds the header line prepended to the outgoing message for a contract. */
export function contractPrefix(contractId: string): string {
  return `${CONTRACT_PREFIX}${contractId}`
}

/**
 * Builds the outgoing message for the given contracts: one header line per
 * contract, then the inline tokens, then the user's text.
 */
export function withContractHeader(text: string, contractIds: string[]): string {
  if (contractIds.length === 0) return text
  const header = contractIds.map((id) => contractPrefix(id)).join('\n')
  return `${header}\n\n${text}`
}

export interface MessageReferences {
  contractIds: string[]
  /** Chat names referenced with `@[name]`. */
  chatNames: string[]
  /** The body with all reference syntax removed. */
  text: string
}

/**
 * Extracts every reference from a message and returns the body with the header
 * lines, contract markers and chat references removed.
 */
export function extractReferences(text: string): MessageReferences {
  const contractIds: string[] = []
  const chatNames: string[] = []
  const contractPattern = new RegExp(
    `${escapeRegExp(CONTRACT_MARKER_START)}([^\\]]+)${escapeRegExp(CONTRACT_MARKER_END)}`,
    'g',
  )

  const cleaned = text
    // Inline contract markers, e.g. `[[contract:cntr-1]]`.
    .replace(contractPattern, (_match, id: string) => {
      contractIds.push(id.trim())
      return ''
    })
    // Contract header lines, e.g. `Пользователь выбрал контракт: cntr-1`.
    .replace(CONTRACT_PREFIX_LINE, (_match, id: string) => {
      contractIds.push(String(id).trim())
      return ''
    })
    // Chat references, e.g. `@[Не приходит счёт]`.
    .replace(CHAT_REFERENCE, (_match, name: string) => {
      chatNames.push(name.trim())
      return ''
    })
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

  return { contractIds: [...new Set(contractIds)], chatNames: [...new Set(chatNames)], text: cleaned }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Short human-readable label for a contract. */
export function contractLabel(contract: SchemaContractOut): string {
  return contract.title || contract.id
}

/** Display name for a referenced chat. */
export function chatLabel(chat: SchemaChatOut): string {
  return chat.title || chat.id
}

/** Lookup of contract id → contract, for resolving names when rendering. */
export function contractsById(contracts: SchemaContractOut[]): Map<string, SchemaContractOut> {
  return new Map(contracts.map((contract) => [contract.id, contract]))
}
