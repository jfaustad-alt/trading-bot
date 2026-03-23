/*
  Formatting utilities for displaying money, percentages, and dates.

  These are used throughout the app to keep number formatting consistent.
  For example, formatMoney(1234.5) → "$1,234.50"
*/

/**
 * Format a number as USD currency.
 * @param {number} value - The dollar amount
 * @param {boolean} showSign - If true, prepend + for positive values
 * @returns {string} Formatted string like "$1,234.50" or "+$50.00"
 */
export function formatMoney(value, showSign = false) {
  if (value == null || isNaN(value)) return '—'
  const sign = showSign && value > 0 ? '+' : ''
  return `${sign}$${Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/**
 * Format a number as a percentage.
 * @param {number} value - The percentage value (e.g. 1.5 means 1.5%)
 * @param {boolean} showSign - If true, prepend + for positive values
 * @returns {string} Formatted string like "+1.50%" or "-0.65%"
 */
export function formatPct(value, showSign = true) {
  if (value == null || isNaN(value)) return '—'
  const sign = showSign && value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

/**
 * Format an ISO timestamp to a short time string.
 * @param {string} isoString - ISO 8601 timestamp
 * @returns {string} Time like "10:32:15 AM"
 */
export function formatTime(isoString) {
  if (!isoString) return '—'
  try {
    return new Date(isoString).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return isoString
  }
}
