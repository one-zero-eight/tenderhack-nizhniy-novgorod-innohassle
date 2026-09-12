import { forwardRef, type ButtonHTMLAttributes } from 'react'
import cva, { type VariantProps } from '@/lib/cva'
import { cn } from '@/lib/cn'

const buttonVariants = cva('flex justify-center items-center text-base text-center cursor-pointer transition-colors duration-100 h-min w-min text-nowrap select-none focus:outline-red/40', {
  variants: {
    size: {
      sm: 'px-5 py-2',
      md: 'px-5 py-3',
    },
    variant: {
      primary: 'font-semibold bg-red text-white hover:bg-[color-mix(in_srgb,var(--color-red),#000_10%)]',
      outline: 'font-semibold border-main-blue/20 border bg-white text-main-blue hover:border-main-blue/50 active:bg-pale-blue/40',
      ghost: 'text-main-blue hover:underline hover:underline-offset-4',
      disabled: 'font-semibold bg-pale-blue text-[color-mix(in_srgb,var(--color-pale-blue),#000_50%)] cursor-not-allowed',
    },
  },
  default: { size: 'md', variant: 'primary' },
})

type ButtonVariantProps = VariantProps<typeof buttonVariants>
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & ButtonVariantProps

const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ children, variant, size, className, disabled, ...props }, ref) => {
  return (
    <button ref={ref} className={cn(buttonVariants({ variant: disabled ? 'disabled' : variant, size, className }))} disabled={disabled} {...props}>
      {children}
    </button>
  )
})

Button.displayName = 'Button'
export default Button
