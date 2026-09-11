import { Combobox, ComboboxInput, ComboboxOption, ComboboxOptions } from '@headlessui/react'
import { useState, useEffect } from 'react'
import { IoSearchSharp } from 'react-icons/io5'
import { $api } from '@/api'
import { cn } from '@/lib/cn'

interface CTEItem {
  cte_id: number
  cte_name: string | null
  category: string | null
  manufacturer: string | null
  characteristics: string | null
}

export type SelectedCTE = { cte_id: number; cte_name: string | null }

interface CTESearchProps {
  value?: string
  onSelect: (cte: SelectedCTE | null) => void
  placeholder?: string
  className?: string
  onlyWithContracts?: boolean
}

function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debouncedValue
}

export default function CTESearch({ value = '', onSelect, placeholder = 'Начните вводить наименование...', className, onlyWithContracts }: CTESearchProps) {
  const [query, setQuery] = useState(value)
  const [selectedCte, setSelectedCte] = useState<SelectedCTE | null>(null)
  const debouncedQuery = useDebounce(query, 150)

  const { data: results = [], isLoading } = $api.useQuery(
    'get',
    '/ctes/search_cte',
    {
      params: { query: { query: debouncedQuery, limit: 50, only_with_contracts: onlyWithContracts } },
    },
    { enabled: debouncedQuery.length >= 1 },
  )

  const ctes = results as CTEItem[]

  return (
    <Combobox<SelectedCTE | null>
      immediate
      value={selectedCte}
      onChange={(v) => {
        const cte = v ?? null
        setSelectedCte(cte)
        onSelect(cte)
        if (cte) setQuery(cte.cte_name ?? '')
      }}
    >
      <div className={cn('relative flex items-center', className)}>
        <IoSearchSharp className="text-gray absolute left-3 size-4 shrink-0" />
        <ComboboxInput
          className="border-gray-blue focus:ring-main-blue w-full border-b-2 py-1.5 pr-3 pl-9 text-sm outline-none"
          displayValue={() => query}
          onChange={(e) => {
            setQuery(e.target.value)
            setSelectedCte(null)
            onSelect(null)
          }}
          placeholder={placeholder}
        />
        <ComboboxOptions className="border-gray-blue absolute top-full right-0 left-0 z-50 mt-1 max-h-72 overflow-auto rounded-md border bg-white shadow-lg">
          {isLoading && <div className="text-gray px-3 py-4 text-sm">Поиск...</div>}
          {!isLoading && ctes.length === 0 && debouncedQuery.length >= 1 && <div className="text-gray px-3 py-4 text-sm">Ничего не найдено</div>}
          {!isLoading &&
            ctes.map((cte, i) => (
              <ComboboxOption key={`${cte.cte_id}-${i}`} value={{ cte_id: cte.cte_id, cte_name: cte.cte_name }} className="hover:text-main-blue cursor-pointer px-3 py-2 text-sm hover:bg-gray-50 data-focus:bg-gray-50">
                <div className="truncate font-medium">{cte.cte_name ?? '—'}</div>
                {(cte.category || cte.manufacturer) && <div className="text-gray truncate text-xs">{[cte.category, cte.manufacturer].filter(Boolean).join(' • ')}</div>}
              </ComboboxOption>
            ))}
        </ComboboxOptions>
      </div>
    </Combobox>
  )
}
