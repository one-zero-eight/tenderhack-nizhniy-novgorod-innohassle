import type { SchemaContractOut } from '@/api/types'

/**
 * Entity aliases inside a message.
 *
 * The backend stores aliases as `@<alias>` with spaces replaced by underscores,
 * e.g. `@[Мой чат]` is persisted as `@Мой_чат` and a contract reference becomes
 * `@cntr-26-004-gk`. On send the composer emits the same form, so a message
 * round-trips unchanged.
 *
 * `extractReferences` parses that form back into contract ids and chat names,
 * resolving each alias against the caller's contracts and chats.
 */

/** Marker wrapped around a contract id while composing, before sending. */
export const CONTRACT_MARKER_START = '[[contract:'
export const CONTRACT_MARKER_END = ']]'

/** Prefix used for the machine-readable contract id inside the composer. */
export const CONTRACT_PREFIX = 'Пользователь выбрал контракт: '

/** Matches the `Пользователь выбрал контракт: <id>` helper line. */
const CONTRACT_PREFIX_LINE = /^Пользователь выбрал контракт:\s*(.+)$/gm

/** Matches an `@[Name with spaces]` reference typed in the composer. */
const BRACKET_REFERENCE = /@\[([^\]]+)\]/g

/** Matches an `@alias` reference (no brackets, no whitespace). */
const PLAIN_REFERENCE = /@([^\s@[\]()]+)/g

/** The underscore the backend substitutes for spaces in an alias. */
const ALIAS_SPACE = '_'

/** Builds the alias the backend expects for a display name. */
export function toAlias(name: string): string {
  return name.trim().replace(/\s+/g, ALIAS_SPACE)
}

/**
 * Builds the inline reference for a contract. Sent as `@<id>`, which is what the
 * backend persists.
 */
export function contractToken(contractId: string): string {
  return `@${toAlias(contractId)}`
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
 * contract (so the backend can attribute them), then the text with the inline
 * contract aliases.
 */
export function withContractHeader(text: string, contractIds: string[]): string {
  if (contractIds.length === 0) return text
  const header = contractIds.map((id) => contractPrefix(id)).join('\n')
  return `${header}\n\n${text}`
}

export interface MessageReferences {
  /** Contracts referenced in the message, resolved by id. */
  contractIds: string[]
  /** Chat names referenced in the message, resolved by name. */
  chatNames: string[]
  /** The body with all reference syntax removed. */
  text: string
}

/** A chat as far as reference resolution is concerned. */
export interface ChatRef {
  id: string
  title: string
}

/** Lookup tables used to tell a contract alias from a chat alias. */
export interface ReferenceSources {
  contracts?: SchemaContractOut[]
  chats?: ChatRef[]
}

/** Normalises a value for loose alias comparison (case, spaces, underscores). */
function normalizeAlias(value: string): string {
  return value.trim().toLowerCase().replace(/[\s_]+/g, ALIAS_SPACE)
}

/**
 * Extracts every reference from a message and returns the body with the helper
 * lines and `@alias` mentions removed.
 *
 * Aliases are matched against the known contracts and chats: an alias equal to a
 * contract id (or its name) becomes a contract reference, likewise for chats.
 * Unrecognised `@mentions` are left in the text untouched.
 */
export function extractReferences(text: string, sources: ReferenceSources = {}): MessageReferences {
  const { contracts = [], chats = [] } = sources

  const contractLookup = new Map<string, string>()
  for (const contract of contracts) {
    contractLookup.set(normalizeAlias(contract.id), contract.id)
    if (contract.title) contractLookup.set(normalizeAlias(contract.title), contract.id)
  }
  const chatLookup = new Map<string, string>()
  for (const chat of chats) {
    chatLookup.set(normalizeAlias(chat.title), chat.title)
    if (chat.id) chatLookup.set(normalizeAlias(chat.id), chat.title)
  }

  const contractIds: string[] = []
  const chatNames: string[] = []

  // Bracket form first: `@[Name with spaces]` maps straight to a chat.
  const withoutBrackets = text.replace(BRACKET_REFERENCE, (_match, rawName: string) => {
    const name = String(rawName).trim()
    const resolved = chatLookup.get(normalizeAlias(name))
    if (resolved) {
      chatNames.push(resolved)
      return ''
    }
    // Unknown bracketed alias: keep the readable name as a chat reference.
    chatNames.push(name.replace(/_/g, ' '))
    return ''
  })

  const cleaned = withoutBrackets
    // Helper lines, e.g. `Пользователь выбрал контракт: cntr-1`.
    .replace(CONTRACT_PREFIX_LINE, (_match, id: string) => {
      const key = normalizeAlias(String(id))
      contractIds.push(contractLookup.get(key) ?? String(id).trim())
      return ''
    })
    // Inline contract markers, still emitted while composing.
    .replace(
      new RegExp(`${escapeRegExp(CONTRACT_MARKER_START)}([^\\]]+)${escapeRegExp(CONTRACT_MARKER_END)}`, 'g'),
      (_match, id: string) => {
        const key = normalizeAlias(String(id))
        contractIds.push(contractLookup.get(key) ?? String(id).trim())
        return ''
      },
    )
    // Plain `@alias` mentions, as persisted by the backend.
    .replace(PLAIN_REFERENCE, (match, alias: string) => {
      const key = normalizeAlias(alias)
      const contractId = contractLookup.get(key)
      if (contractId) {
        contractIds.push(contractId)
        return ''
      }
      const chatName = chatLookup.get(key)
      if (chatName) {
        chatNames.push(chatName)
        return ''
      }
      // Not a known reference: leave it in the text.
      return match
    })
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

  return {
    contractIds: [...new Set(contractIds)],
    chatNames: [...new Set(chatNames)],
    text: cleaned,
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Short human-readable label for a contract. */
export function contractLabel(contract: SchemaContractOut): string {
  return contract.title || contract.id
}

/** Display name for a referenced chat. */
export function chatLabel(chat: ChatRef): string {
  return chat.title || chat.id
}

/** Lookup of contract id → contract, for resolving names when rendering. */
export function contractsById(contracts: SchemaContractOut[]): Map<string, SchemaContractOut> {
  return new Map(contracts.map((contract) => [contract.id, contract]))
}
