import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useRouteError } from 'react-router'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'

/** Readable Ukrainian fallback shown instead of a blank screen after a render crash. */
export function CrashFallback() {
  return (
    <div role="alert" className="flex h-full min-h-60 items-center justify-center p-6">
      <div className="max-w-md space-y-3 text-center">
        <h1 className="text-base font-semibold">{uk.errorBoundary.title}</h1>
        <p className="text-muted-foreground">{uk.errorBoundary.description}</p>
        <div className="flex justify-center gap-2 pt-1">
          <Button size="sm" onClick={() => window.location.reload()}>
            {uk.errorBoundary.reload}
          </Button>
          <Button size="sm" variant="outline" onClick={() => window.location.assign('/')}>
            {uk.errorBoundary.backHome}
          </Button>
        </div>
      </div>
    </div>
  )
}

/** Route-level error element: react-router catches render errors inside routes itself. */
export function RouteErrorFallback() {
  const error = useRouteError()
  console.error(error)
  return <CrashFallback />
}

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

/** Top-level boundary for crashes outside the router (providers, layout shell). */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(error, info.componentStack)
  }

  render(): ReactNode {
    if (this.state.hasError) return <CrashFallback />
    return this.props.children
  }
}
