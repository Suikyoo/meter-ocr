async function getJson(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`)
  return res.json()
}

export function fetchDevices() {
  return getJson('/api/devices')
}

export function fetchConsumption(id, period, anchor) {
  const q = new URLSearchParams({ period })
  if (anchor) q.set('anchor', anchor)
  return getJson(`/api/devices/${encodeURIComponent(id)}/consumption?${q}`)
}
