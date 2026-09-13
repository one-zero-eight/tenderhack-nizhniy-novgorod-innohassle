import { cn } from '@/lib/cn'
import type { SchemaContractOut } from '@/api/types'
import { contractLabel } from '@/lib/contracts'

interface ContractMentionMenuProps {
  contracts: SchemaContractOut[]
  /** Index of the highlighted option (keyboard navigation). */
  activeIndex: number
  onSelect: (contract: SchemaContractOut) => void
  onHover: (index: number) => void
  className?: string
}

/**
 * Popup listing contracts matching the token typed after `@`.
 *
 * Keyboard handling lives in the composer (Tab/Enter accept, arrows move), so
 * this component is presentational apart from reporting hovers.
 */
export default function ContractMentionMenu({
  contracts,
  activeIndex,
  onSelect,
  onHover,
  className,
}: ContractMentionMenuProps) {
  if (contracts.length === 0) return null

  return (
    <div
      role="listbox"
      aria-label="Контракты"
      className={cn(
        'absolute bottom-full left-0 z-30 mb-1 max-h-64 w-full overflow-auto border border-gray-blue bg-white shadow-lg',
        className,
      )}
    >
      <div className="text-gray border-gray-blue border-b px-3 py-1.5 text-[0.6875rem] font-semibold tracking-wide uppercase">
        Контракты
      </div>
      {contracts.map((contract, index) => (
        <button
          key={contract.id}
          type="button"
          role="option"
          aria-selected={index === activeIndex}
          onMouseEnter={() => onHover(index)}
          // `onMouseDown` fires before the textarea loses focus, so the caret
          // position is still valid when the composer inserts the token.
          onMouseDown={(event) => {
            event.preventDefault()
            onSelect(contract)
          }}
          className={cn(
            'flex w-full flex-col gap-0.5 px-3 py-2 text-left transition-colors',
            index === activeIndex ? 'bg-pale-blue/70' : undefined,
          )}
        >
          <span className="text-black truncate text-sm font-medium">{contractLabel(contract)}</span>
          <span className="text-gray flex items-center gap-2 text-xs">
            <span className="font-mono">{contract.id}</span>
            <span aria-hidden="true">·</span>
            <span className="truncate">{contract.status}</span>
          </span>
        </button>
      ))}
    </div>
  )
}
