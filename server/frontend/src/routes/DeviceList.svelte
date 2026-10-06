<script>
  import { fetchDevices } from '../lib/api.js'
  import { formatKwh, since } from '../lib/format.js'
  import { poll } from '../lib/poll.js'
  import StatusBadge from '../lib/StatusBadge.svelte'

  let devices = $state(null)
  let error = $state(false)
  let now = $state(Date.now())

  async function load() {
    try {
      devices = await fetchDevices()
      error = false
    } catch {
      error = true
    }
    now = Date.now()
  }

  $effect(() => {
    load()
    return poll(load, 30000)
  })

  function detail(d) {
    const value = d.last_value == null ? 'No reading yet' : `${formatKwh(d.last_value)} kWh`
    const t = since(d.last_seen, now)
    return `${value} · ${d.online === false ? `offline ${t}` : `${t} ago`}`
  }
</script>

<header class="bar"><h1>Meters</h1></header>
{#if error}
  <div class="banner" role="alert">Couldn't load. <button onclick={load}>Retry</button></div>
{/if}
<main>
  {#if devices === null}
    {#if !error}
      <div class="skeleton line"></div>
      <div class="skeleton line"></div>
    {/if}
  {:else if devices.length === 0}
    <p class="empty">No meters yet. Devices appear here once they connect to the MQTT broker.</p>
  {:else}
    <ul class="list">
      {#each devices as d (d.id)}
        <li>
          <a class="row" href="#/device/{encodeURIComponent(d.id)}">
            <span class="title"><StatusBadge online={d.online} compact /> {d.name ?? d.id}</span>
            <span class="sub">{detail(d)}</span>
            <span class="chev" aria-hidden="true">›</span>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</main>
