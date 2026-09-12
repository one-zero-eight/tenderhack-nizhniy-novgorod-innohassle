import { cn } from '@/lib/cn'

/**
 * Shared navbar item styling: square corners, transparent background, and a
 * 1px gray border on the left and right only.
 */
export function navButtonClasses(isActive = false, className?: string): string {
  return cn(
    'border-gray-blue border-x bg-transparent px-5 text-sm font-medium no-underline transition-colors',
    'flex h-full items-center justify-center gap-2',
    isActive ? 'text-main-blue' : 'text-pale-black hover:bg-pale-blue/50 hover:text-main-blue',
    className,
  )
}
