import { Routes, Route } from 'react-router-dom'
import TabBar from './components/TabBar'
import Live from './pages/Live'
import Backtests from './pages/Backtests'
import Analysis from './pages/Analysis'
import History from './pages/History'
import Settings from './pages/Settings'

/*
  App — the root component.

  It renders the tab bar (always visible at the bottom) and a
  <Routes> block that swaps the page content based on the URL.
  React Router handles this client-side — no page reloads.
*/

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<Live />} />
        <Route path="/backtests" element={<Backtests />} />
        <Route path="/analysis" element={<Analysis />} />
        <Route path="/history" element={<History />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
      <TabBar />
    </>
  )
}
