import type { ReactNode } from 'react'

interface PagePlaceholderProps {
  title: string
  description: string
  children?: ReactNode
}

/** Page header + empty state used by pages that are not built yet. */
export function PagePlaceholder({ title, description, children }: PagePlaceholderProps) {
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
      <div className="flex min-h-40 flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-6 py-10 text-center">
        <p className="max-w-lg text-muted-foreground">{description}</p>
        {children}
      </div>
    </section>
  )
}
