// French number formatting — the UI must not print "19.98" where it means 19,98.

const cache = new Map<string, Intl.NumberFormat>()

function nf(min: number, max: number): Intl.NumberFormat {
  const key = `${min}:${max}`
  let f = cache.get(key)
  if (!f) {
    f = new Intl.NumberFormat('fr-FR', {
      minimumFractionDigits: min,
      maximumFractionDigits: max,
    })
    cache.set(key, f)
  }
  return f
}

export function fmtNumber(value: number, maxDigits = 0): string {
  return nf(0, maxDigits).format(value)
}

export function fmtFixed(value: number, digits = 2): string {
  return nf(digits, digits).format(value)
}

export function fmtPercent(value: number, digits = 1): string {
  return `${value > 0 ? '+' : ''}${nf(digits, digits).format(value)} %`
}
