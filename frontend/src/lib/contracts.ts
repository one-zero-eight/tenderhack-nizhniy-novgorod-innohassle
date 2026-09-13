import type { SchemaContractOut } from '@/api/types'

/**
 * Contracts are attached to a message as plain text, because the chat API has
 * no contract attachment type:
 *
 *   Пользователь выбрал контракт: cntr-26-004-gk
 *   [[contract:cntr-26-004-gk]]
 *
 *   <user text>
 *
 * The UI strips both forms from the rendered body and shows the contract as an
 * attachment chip instead, resolving its display name from the contracts list.
 */

/** Marker wrapped around the contract id inside the message body. */
export const CONTRACT_MARKER_START = '[[contract:'
export const CONTRACT_MARKER_END = ']]'

/** Prefix used for the machine-readable header line, e.g. for the backend. */
export const CONTRACT_PREFIX = 'Пользователь выбрал контракт: '

/** Matches the `Пользователь выбрал контракт: <id>` header line. */
const CONTRACT_PREFIX_LINE = /^Пользователь выбрал контракт:\s*(.+)$/gm

/** Builds the inline token for a contract id. */
export function contractToken(contractId: string): string {
  return `${CONTRACT_MARKER_START}${contractId}${CONTRACT_MARKER_END}`
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

/**
 * Extracts contract ids referenced in a message and returns the body with both
 * the header lines and the inline markers removed, so nothing contract-related
 * leaks into the rendered text.
 */
export function extractContracts(text: string): { contractIds: string[]; text: string } {
  const ids: string[] = []
  const pattern = new RegExp(
    `${escapeRegExp(CONTRACT_MARKER_START)}([^\\]]+)${escapeRegExp(CONTRACT_MARKER_END)}`,
    'g',
  )

  const cleaned = text
    // Inline markers, e.g. `[[contract:cntr-1]]`.
    .replace(pattern, (_match, id: string) => {
      ids.push(id.trim())
      return ''
    })
    // Header lines, e.g. `Пользователь выбрал контракт: cntr-1`.
    .replace(CONTRACT_PREFIX_LINE, (_match, id: string) => {
      ids.push(String(id).trim())
      return ''
    })
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

  return { contractIds: [...new Set(ids)], text: cleaned }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Short human-readable label for a contract. */
export function contractLabel(contract: SchemaContractOut): string {
  return contract.title || contract.id
}

/** Lookup of contract id → contract, for resolving names when rendering. */
export function contractsById(contracts: SchemaContractOut[]): Map<string, SchemaContractOut> {
  return new Map(contracts.map((contract) => [contract.id, contract]))
}
