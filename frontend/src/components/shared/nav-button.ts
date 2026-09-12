import { cn } from '@/lib/cn'

/**
 * Shared navbar item styling: square corners and a transparent background.
 */
export function navButtonClasses(isActive = false, className?: string): string {
  return cn(
    'bg-transparent px-5 text-sm font-medium no-underline transition-colors',
    'flex h-full items-center justify-center gap-2',
    isActive ? 'text-main-blue' : 'text-pale-black hover:bg-pale-blue/50 hover:text-main-blue',
    className,
  )
}
