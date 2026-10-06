<script>
  import { BarController, BarElement, CategoryScale, Chart, LinearScale, Tooltip } from 'chart.js'
  import { formatKwh } from './format.js'

  Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip)

  let { labels, titles, values, unit } = $props()
  let canvas
  let chart

  $effect(() => {
    const css = getComputedStyle(document.documentElement)
    const color = (name) => css.getPropertyValue(name).trim()
    chart = new Chart(canvas, {
      type: 'bar',
      data: { labels: [], datasets: [{ data: [], backgroundColor: color('--accent'), borderRadius: 3, maxBarThickness: 32 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => titles[items[0].dataIndex],
              label: (item) => `${formatKwh(item.parsed.y)} ${unit}`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: color('--muted'), maxRotation: 0, autoSkip: true } },
          y: { beginAtZero: true, grid: { color: color('--line') }, ticks: { color: color('--muted') } },
        },
      },
    })
    return () => chart.destroy()
  })

  $effect(() => {
    chart.data.labels = labels
    chart.data.datasets[0].data = values
    chart.update()
  })
</script>

<div class="chart" role="img" aria-label="Consumption per period">
  <canvas bind:this={canvas}></canvas>
</div>
