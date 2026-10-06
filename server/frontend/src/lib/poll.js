// Calls fn every `ms` while the page is visible, and right away when it becomes visible again.
// Returns a function that stops polling.
export function poll(fn, ms) {
  const visible = () => document.visibilityState === 'visible'
  const timer = setInterval(() => { if (visible()) fn() }, ms)
  const onChange = () => { if (visible()) fn() }
  document.addEventListener('visibilitychange', onChange)
  return () => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', onChange)
  }
}
