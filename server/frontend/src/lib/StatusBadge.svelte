<script>
  let { online, compact = false } = $props()
  const label = $derived(online === true ? 'online' : online === false ? 'offline' : 'status unknown')
</script>

<span class="badge" class:online={online === true} class:compact title={label}>
  <span class="dot" aria-hidden="true"></span>{#if compact}<span class="visually-hidden">{label}</span>{:else}{label}{/if}
</span>

<style>
  .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: currentColor;
  }
  .badge:not(.online) .dot { background: transparent; box-shadow: inset 0 0 0 2px currentColor; }
  .visually-hidden {
    position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip: rect(0 0 0 0); white-space: nowrap;
  }
</style>
