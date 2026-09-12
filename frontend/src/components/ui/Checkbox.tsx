import { forwardRef } from 'react'
import { cn } from '@/lib/cn'

interface CheckboxProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: React.ReactNode
  className?: string
}

const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(({ label, className, ...props }, ref) => (
  <label className={cn('text-black flex cursor-pointer items-center gap-2 text-sm', className)}>
    <input ref={ref} type="checkbox" className="border-gray-300 rounded focus:ring-main-blue/40" {...props} />
    {label}
  </label>
))

Checkbox.displayName = 'Checkbox'
export default Checkbox
