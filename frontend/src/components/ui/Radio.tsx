import { forwardRef } from 'react'
import { cn } from '@/lib/cn'

interface RadioProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: React.ReactNode
  className?: string
}

const Radio = forwardRef<HTMLInputElement, RadioProps>(({ label, className, ...props }, ref) => (
  <label className={cn('text-black flex cursor-pointer items-center gap-2 text-sm', className)}>
    <input ref={ref} type="radio" className="border-gray-300 focus:ring-main-blue/40" {...props} />
    {label}
  </label>
))

Radio.displayName = 'Radio'
export default Radio
