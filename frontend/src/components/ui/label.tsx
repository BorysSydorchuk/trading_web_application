import * as React from 'react'

import { cn } from '@/lib/utils'

/** shadcn/ui Label without the Radix dependency (a plain <label> is enough here). */
function Label({ className, ...props }: React.ComponentProps<'label'>) {
  return (
    <label
      data-slot="label"
      className={cn(
        'flex items-center gap-1 text-xs leading-none font-medium text-muted-foreground select-none peer-disabled:cursor-not-allowed peer-disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}

export { Label }
