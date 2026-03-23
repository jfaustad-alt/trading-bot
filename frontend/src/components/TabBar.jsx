import { NavLink } from 'react-router-dom'
import './TabBar.css'

/*
  Bottom tab bar — the main navigation for the app.

  NavLink from react-router automatically adds an "active" class
  to whichever tab matches the current URL, so the selected tab
  gets highlighted without us tracking state manually.
*/

const tabs = [
  { path: '/',          label: 'Live',      icon: '◉' },
  { path: '/backtests', label: 'Backtests',  icon: '⟳' },
  { path: '/analysis',  label: 'Analysis',   icon: '◈' },
  { path: '/history',   label: 'History',    icon: '☰' },
  { path: '/settings',  label: 'Settings',   icon: '⚙' },
]

export default function TabBar() {
  return (
    <nav className="tab-bar">
      {tabs.map((tab) => (
        <NavLink
          key={tab.path}
          to={tab.path}
          end={tab.path === '/'}
          className={({ isActive }) =>
            `tab-item ${isActive ? 'tab-active' : ''}`
          }
        >
          <span className="tab-icon">{tab.icon}</span>
          <span className="tab-label">{tab.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
