// Dates from the API carry the server's offset. Labels use the date and time text as written,
// so they show server-local time no matter what zone the phone is in.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December']
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

const kwh = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

export function formatKwh(v) {
  return v == null ? '—' : kwh.format(v)
}

export function since(iso, nowMs = Date.now()) {
  const s = Math.max(0, Math.round((nowMs - Date.parse(iso)) / 1000))
  if (s < 60) return '<1 min'
  if (s < 3600) return `${Math.floor(s / 60)} min`
  if (s < 86400) return `${Math.floor(s / 3600)} h`
  return `${Math.floor(s / 86400)} d`
}

function parts(iso, dayOffset = 0) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  const t = new Date(Date.UTC(y, m - 1, d + dayOffset))
  return { y: t.getUTCFullYear(), m: t.getUTCMonth(), d: t.getUTCDate(), dow: t.getUTCDay() }
}

const short = (p) => `${MONTHS[p.m]} ${p.d}`

export function windowLabel(period, startIso, endIso) {
  const s = parts(startIso)
  switch (period) {
    case 'hour': return `${DAYS[s.dow]}, ${short(s)} ${s.y}`
    case 'day': return `${MONTHS_LONG[s.m]} ${s.y}`
    case 'week': {
      const e = parts(endIso, -1)
      return s.y === e.y ? `${short(s)} – ${short(e)} ${e.y}` : `${short(s)} ${s.y} – ${short(e)} ${e.y}`
    }
    case 'month': return String(s.y)
    default: return 'All years'
  }
}

export function bucketLabel(period, iso) {
  const p = parts(iso)
  switch (period) {
    case 'hour': return iso.slice(11, 16)
    case 'day': return String(p.d)
    case 'week': return short(p)
    case 'month': return MONTHS[p.m]
    default: return String(p.y)
  }
}

export function tooltipTitle(period, iso) {
  const p = parts(iso)
  switch (period) {
    case 'hour': {
      const h = Number(iso.slice(11, 13))
      return `${short(p)}, ${String(h).padStart(2, '0')}:00–${String(h + 1).padStart(2, '0')}:00`
    }
    case 'day': return `${DAYS[p.dow]}, ${short(p)}`
    case 'week': return `Week of ${short(p)}`
    case 'month': return `${MONTHS_LONG[p.m]} ${p.y}`
    default: return String(p.y)
  }
}

const NOUNS = { hour: 'this day', day: 'this month', week: 'these 12 weeks', month: 'this year' }

export function periodNoun(period) {
  return NOUNS[period] ?? 'in total'
}

export function dateTime(iso) {
  return `${short(parts(iso))}, ${iso.slice(11, 16)}`
}
