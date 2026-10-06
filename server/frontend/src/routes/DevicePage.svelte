<script>
  import { fetchConsumption, fetchDevices } from '../lib/api.js'
  import { bucketLabel, dateTime, formatKwh, periodNoun, tooltipTitle, windowLabel } from '../lib/format.js'
  import { poll } from '../lib/poll.js'
  import BarChart from '../lib/BarChart.svelte'
  import StatusBadge from '../lib/StatusBadge.svelte'

  let { id } = $props()

  const PERIODS = [['hour', 'Hourly'], ['day', 'Daily'], ['week', 'Weekly'], ['month', 'Monthly'], ['year', 'Yearly']]

  let period = $state('hour')
  let anchor = $state(null) // null = today (server decides)
  let data = $state(null)
  let device = $state(null)
  let error = $state(false)

  async function load() {
    const p = period
    const a = anchor
    try {
      const [consumption, devices] = await Promise.all([fetchConsumption(id, p, a), fetchDevices()])
      if (p !== period || a !== anchor) return // a newer request owns the screen
      data = consumption
      device = devices.find((d) => d.id === id) ?? null
      error = false
    } catch {
      error = true
    }
  }

  $effect(() => {
    period
    anchor
    load()
  })

  $effect(() => poll(load, 30000))

  const chart = $derived(data && {
    labels: data.buckets.map((b) => bucketLabel(data.period, b.start)),
    titles: data.buckets.map((b) => tooltipTitle(data.period, b.start)),
    values: data.buckets.map((b) => b.consumption),
  })
</script>

<header class="bar">
  <a class="back" href="#/" aria-label="All meters">‹</a>
  <h1>{device?.name ?? id}</h1>
  {#if device}<StatusBadge online={device.online} />{/if}
</header>
{#if error}
  <div class="banner" role="alert">Couldn't load. <button onclick={load}>Retry</button></div>
{/if}
<main>
  {#if device?.ip}
    <a class="setup" href="http://{device.ip}/" target="_blank" rel="noopener">Setup page ↗</a>
  {/if}

  <div class="segments" role="tablist" aria-label="Partition">
    {#each PERIODS as [p, label] (p)}
      <button role="tab" aria-selected={period === p} class:active={period === p} onclick={() => (period = p)}>
        {label}
      </button>
    {/each}
  </div>

  {#if data}
    <nav class="window" aria-label="Time window">
      <button aria-label="Previous" disabled={!data.prev_anchor} onclick={() => (anchor = data.prev_anchor)}>‹</button>
      <span>{windowLabel(data.period, data.window_start, data.window_end)}</span>
      <button aria-label="Next" disabled={!data.next_anchor} onclick={() => (anchor = data.next_anchor)}>›</button>
    </nav>

    <section class="total">
      <p class="big">{formatKwh(data.total)} <span class="unit">{data.unit}</span></p>
      <p class="muted">used {periodNoun(data.period)}</p>
      {#if data.differential}
        <p class="diff">{formatKwh(data.differential.start_value)} → {formatKwh(data.differential.end_value)} {data.unit}</p>
      {/if}
      {#if data.has_reset}
        <p class="note">Meter reset in this period. Total excludes the jump.</p>
      {/if}
    </section>

    <BarChart labels={chart.labels} titles={chart.titles} values={chart.values} unit={data.unit} />

    {#if data.current}
      <p class="muted">Meter now: {formatKwh(data.current.value)} {data.unit} · {dateTime(data.current.ts)}</p>
    {/if}
  {:else if !error}
    <div class="skeleton line"></div>
    <div class="skeleton block"></div>
  {/if}
</main>
