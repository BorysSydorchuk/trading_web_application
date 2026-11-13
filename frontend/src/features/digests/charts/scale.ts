/** Maps [min, max] onto [from, to]; a flat range maps to the middle (geometry only). */
export function linearScale(min: number, max: number, from: number, to: number): (value: number) => number {
  if (max === min) return () => (from + to) / 2
  return (value) => from + ((value - min) / (max - min)) * (to - from)
}
