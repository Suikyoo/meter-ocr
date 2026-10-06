<script>
  let { online, compact = false } = $props()
  const label = $derived(online === true ? 'online' : online === false ? 'offline' : 'status unknown')
  const glyph = $derived(online === true ? '●' : online === false ? '○' : '◌')
</script>

<span class="badge" class:online={online === true} title={label}>
  <span aria-hidden="true">{glyph}</span>{#if compact}<span class="visually-hidden">{label}</span>{:else}{' '}{label}{/if}
</span>

<style>
  .visually-hidden {
    position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip: rect(0 0 0 0); white-space: nowrap;
  }
</style>
