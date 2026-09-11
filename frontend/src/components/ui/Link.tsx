import { Link as TanstackLink, type LinkComponentProps as TanstackLinkComponentProps } from '@tanstack/react-router'

export default function Link({ children, ...props }: TanstackLinkComponentProps) {
  return (
    <TanstackLink className="text-sea-dark hover:text-sea-clear underline" {...props}>
      {children}
    </TanstackLink>
  )
}
