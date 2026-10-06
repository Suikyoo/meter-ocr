<script>
  import DeviceList from './routes/DeviceList.svelte'
  import DevicePage from './routes/DevicePage.svelte'

  const PREFIX = '#/device/'
  let hash = $state(location.hash)

  $effect(() => {
    const onChange = () => (hash = location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  })

  const deviceId = $derived(hash.startsWith(PREFIX) ? decodeURIComponent(hash.slice(PREFIX.length)) : null)
</script>

{#if deviceId}
  {#key deviceId}
    <DevicePage id={deviceId} />
  {/key}
{:else}
  <DeviceList />
{/if}
