import { Listbox, ListboxButton, ListboxOption, ListboxOptions } from '@headlessui/react'
import { cn } from '@/lib/cn'
import { IoChevronDown } from 'react-icons/io5'

interface DropdownOption<T> {
  value: T
  label: string
}

interface DropdownProps<T> {
  options: DropdownOption<T>[]
  value: T | null
  onChange: (value: T) => void
  placeholder?: string
  className?: string
  disabled?: boolean
}

export default function Dropdown<T extends string | number>({ options, value, onChange, placeholder = 'Выберите...', className, disabled }: DropdownProps<T>) {
  const selected = options.find((o) => o.value === value)
  return (
    <Listbox value={value ?? undefined} onChange={onChange} disabled={disabled}>
      <div className={cn('relative', className)}>
        <ListboxButton className="border-gray-blue focus:ring-main-blue flex h-full w-full items-center justify-between gap-2 border-2 px-4 py-2 text-left text-sm outline-none">
          <span className={cn('truncate', selected ? undefined : 'text-gray')}>{selected?.label ?? placeholder}</span>
          <IoChevronDown className="size-4 shrink-0 text-gray" />
        </ListboxButton>
        <ListboxOptions className="border-gray-blue absolute top-full left-0 right-0 z-50 mt-1 max-h-48 overflow-auto rounded-md border bg-white shadow-lg">
          {options.map((opt) => (
            <ListboxOption key={String(opt.value)} value={opt.value} className="hover:text-main-blue cursor-pointer px-3 py-2 text-sm hover:bg-gray-50 data-focus:bg-gray-50">
              {opt.label}
            </ListboxOption>
          ))}
        </ListboxOptions>
      </div>
    </Listbox>
  )
}
