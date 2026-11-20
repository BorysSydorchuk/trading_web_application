import * as React from 'react'
import { ChevronDownIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

/** shadcn/ui NativeSelect: a styled <select>, keyboard and screen-reader friendly by default. */
function NativeSelect({
  className,
  wrapperClassName,
  ...props
}: React.ComponentProps<'select'> & { wrapperClassName?: string }) {
  return (
    <div className={cn('relative w-full', wrapperClassName)} data-slot="native-select-wrapper">
      <select
        data-slot="native-select"
        className={cn(
          'border-input h-8 w-full min-w-0 appearance-none rounded-md border bg-surface py-1 pr-8 pl-2.5 text-sm shadow-xs transition-[color,box-shadow] outline-none disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50',
          'focus-visible:border-ring focus-visible:ring-ring focus-visible:ring-[3px]',
          'aria-invalid:ring-destructive/20 aria-invalid:border-destructive',
          '[&>option]:bg-popover [&>option]:text-popover-foreground',
          className,
        )}
        {...props}
      />
      <ChevronDownIcon
        className="text-muted-foreground pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2"
        aria-hidden
      />
    </div>
  )
}

export { NativeSelect }
