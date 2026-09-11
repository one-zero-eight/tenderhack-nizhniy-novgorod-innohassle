import { Combobox, ComboboxInput, ComboboxOption, ComboboxOptions } from '@headlessui/react'
import { useState, useMemo } from 'react'
import { cn } from '@/lib/cn'
import { IoSearchSharp } from 'react-icons/io5'

interface RegionSearchProps {
  options: string[]
  value?: string
  onSelect: (value: string) => void
  placeholder?: string
  className?: string
}

export default function RegionSearch({ options, value = '', onSelect, placeholder = 'Начните вводить регион...', className }: RegionSearchProps) {
  const [query, setQuery] = useState(value)
  const filtered = useMemo(() => (query === '' ? options : options.filter((r) => r.toLowerCase().includes(query.toLowerCase()))), [options, query])

  return (
    <Combobox
      immediate
      value={query}
      onChange={(v) => {
        const s = v ?? ''
        onSelect(s)
        setQuery(s)
      }}
    >
      <div className={cn('relative flex items-center', className)}>
        <IoSearchSharp className="text-gray absolute left-3 size-4 shrink-0" />
        <ComboboxInput className="border-gray-blue focus:ring-main-blue w-full border-b-2 py-1.5 pr-3 pl-9 text-sm outline-none" displayValue={() => query} onChange={(e) => setQuery(e.target.value)} placeholder={placeholder} />
        <ComboboxOptions className="border-gray-blue absolute top-full right-0 left-0 z-50 max-h-64 overflow-auto border border-t-0 bg-white shadow-lg">
          {filtered.map((region) => (
            <ComboboxOption key={region} value={region} className="hover:text-main-blue cursor-pointer px-3 py-2 text-sm hover:bg-gray-100">
              {region}
            </ComboboxOption>
          ))}
        </ComboboxOptions>
      </div>
    </Combobox>
  )
}
