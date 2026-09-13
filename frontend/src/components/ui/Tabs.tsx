import { cn } from '@/lib/cn'

export interface TabItem<T extends string> {
  value: T
  label: string
  /** Optional count shown next to the label. */
  count?: number
}

interface TabsProps<T extends string> {
  tabs: TabItem<T>[]
  value: T
  onChange: (value: T) => void
  className?: string
}

/**
 * Horizontal tab bar. The active tab is marked with a red underline, matching
 * the portal's tab treatment (no pill backgrounds, no rounding).
 */
export default function Tabs<T extends string>({ tabs, value, onChange, className }: TabsProps<T>) {
  return (
    <div className={cn('border-gray-blue flex flex-wrap gap-1 border-b', className)} role="tablist">
      {tabs.map((tab) => {
        const active = tab.value === value
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.value)}
            className={cn(
              'relative -mb-px border-b-[3px] px-4 py-2.5 text-sm font-semibold transition-colors',
              active ? 'border-red text-black' : 'text-gray hover:text-black border-transparent',
            )}
          >
            <span className="flex items-center gap-2">
              {tab.label}
              {tab.count !== undefined && (
                <span className={cn('text-xs font-medium', active ? 'text-gray' : 'text-gray')}>{tab.count}</span>
              )}
            </span>
          </button>
        )
      })}
    </div>
  )
}
