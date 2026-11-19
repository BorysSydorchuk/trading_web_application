/**
 * `setupUser`: the one way component tests create a user-event instance (M8-17).
 *
 * user-event's default `delay: 0` waits for a timer task after every keystroke, so typing
 * "Тиск покупців" queues 13 timer tasks behind React/MSW work. On a CPU-starved test worker
 * (full gate right after the backend run, all cores busy) each wait grows, and long typing
 * flows crossed the 5 s test timeout (BiasNotePage, DigestPageEditing, DescribePage).
 * `delay: null` dispatches the same events per key (keydown, input, keyup, each wrapped in
 * act) without the timer waits: same behaviour under test, about 3x faster, load-independent.
 * `advanceTimers` only matters for a test that overrides `delay` (there are no per-key waits).
 */
import userEvent from '@testing-library/user-event'

type Options = NonNullable<Parameters<typeof userEvent.setup>[0]>

export function setupUser(options: Options = {}) {
  return userEvent.setup({ delay: null, ...options })
}
