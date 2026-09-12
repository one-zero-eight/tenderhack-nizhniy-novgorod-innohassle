import { cn } from '@/lib/cn'
import cva, { type VariantProps } from '@/lib/cva'
import { forwardRef, type InputHTMLAttributes } from 'react'

const inputVariants = cva('block w-full border-2 border-pale-blue px-5 py-2 text-md placeholder:text-pale-black disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:none transition-colors', {
  variants: {
    variant: {
      outline: 'text-black bg-white',
      fill: 'text-black bg-pale-blue',
      disabled: 'bg-secondary cursor-not-allowed',
    },
    size: {
      sm: 'px-2 py-1 text-xs',
      md: 'px-3 py-2 text-sm',
      lg: 'px-4 py-3 text-base',
    },
  },
  default: {
    intent: 'outline',
    size: 'md',
  },
})

type InputPropsVariants = VariantProps<typeof inputVariants>
type InputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> & InputPropsVariants & { label?: string | null }

const Input = forwardRef<HTMLInputElement, InputProps>(({ className, variant, size, label = null, disabled, ...props }, ref) => {
  return (
    <div className="w-full space-y-2">
      {label && <label className="text-black mb-2 block text-sm font-medium">{label}</label>}
      <input ref={ref} className={cn('flex h-full w-full flex-row items-center bg-transparent outline-none select-none', inputVariants({ variant: disabled ? 'disabled' : variant, size, className }))} disabled={disabled} {...props} />
    </div>
  )
})

Input.displayName = 'Input'
export default Input
