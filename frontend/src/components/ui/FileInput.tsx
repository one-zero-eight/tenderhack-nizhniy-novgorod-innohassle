import { useRef, useState, forwardRef, type ComponentProps, useImperativeHandle } from 'react'
import Button from './Button'
import { MdOutlineUploadFile } from 'react-icons/md'

export type FileInputProps = {
  buttonLabel?: string
  onFileChange?: (files: FileList | null) => void
  className?: string
} & ComponentProps<'input'>

const FileInput = forwardRef<HTMLInputElement, FileInputProps>(({ buttonLabel = 'Choose File', onFileChange, className = '', ...props }, ref) => {
  const inputRef = useRef<HTMLInputElement>(null)
  const [, setFileInfos] = useState<{ name: string; size: number }[] | null>(null)

  useImperativeHandle(ref, () => inputRef.current as HTMLInputElement)

  const handleClick = () => {
    inputRef.current?.click()
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    onFileChange?.(files)
    props.onChange?.(e as React.ChangeEvent<HTMLInputElement>)
    if (files && files.length > 0) {
      setFileInfos(Array.from(files).map((file) => ({ name: file.name, size: file.size })))
    } else {
      setFileInfos(null)
    }
  }

  return (
    <div className={`flex items-center gap-4 ${className}`}>
      <Button variant="primary" size="sm" onClick={handleClick} className="flex items-center gap-2">
        <MdOutlineUploadFile className="size-5" />
        {buttonLabel}
      </Button>
      <input type="file" ref={inputRef} className="hidden" {...props} onChange={handleChange} />
    </div>
  )
})

export default FileInput
