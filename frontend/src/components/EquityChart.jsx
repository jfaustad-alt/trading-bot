import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
} from 'chart.js'

// Register the Chart.js components we need.
// Chart.js is modular — you only import what you use, keeping the bundle small.
ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip)

/*
  EquityChart — line chart showing portfolio value over time.

  Props:
    data: Array of { date, equity } or { date, rating }
    label: Chart label (e.g. "Equity" or "ELO Rating")
    color: Line color (CSS color string)
*/

export default function EquityChart({ data, label, color = '#00e676' }) {
  if (!data || data.length < 2) {
    return (
      <div className="chart-container" style={{ textAlign: 'center', padding: '40px' }}>
        <span className="text-muted">Not enough data for chart</span>
      </div>
    )
  }

  const chartData = {
    labels: data.map((d) => d.date),
    datasets: [
      {
        label,
        data: data.map((d) => d.equity ?? d.rating),
        borderColor: color,
        backgroundColor: color + '20',
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        pointHitRadius: 10,
        borderWidth: 2,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      intersect: false,
      mode: 'index',
    },
    plugins: {
      tooltip: {
        backgroundColor: '#1a1a3e',
        titleColor: '#e8e8f0',
        bodyColor: '#e8e8f0',
        borderColor: '#2a2a4e',
        borderWidth: 1,
        padding: 10,
        cornerRadius: 8,
        titleFont: { family: 'Inter' },
        bodyFont: { family: 'JetBrains Mono' },
      },
    },
    scales: {
      x: {
        display: true,
        ticks: {
          color: '#606080',
          font: { size: 10 },
          maxTicksLimit: 6,
        },
        grid: { display: false },
      },
      y: {
        display: true,
        ticks: {
          color: '#606080',
          font: { size: 10, family: 'JetBrains Mono' },
        },
        grid: {
          color: '#2a2a4e',
          drawBorder: false,
        },
      },
    },
  }

  return (
    <div className="chart-container" style={{ height: 220 }}>
      <canvas style={{ display: 'none' }} />
      <Line data={chartData} options={options} />
    </div>
  )
}
