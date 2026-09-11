import { CgSpinnerTwo } from 'react-icons/cg'
import { cn } from '@/lib/cn'

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const sizeClasses = {
  sm: 'size-4',
  md: 'size-6',
  lg: 'size-8',
}

export default function LoadingSpinner({ size = 'md', className }: LoadingSpinnerProps) {
  return <CgSpinnerTwo className={cn('animate-spin', sizeClasses[size], className)} aria-label="Загрузка" />
}
