import { describe, expect, it } from 'vitest'
import {
  bucketLabel, dateTime, formatKwh, periodNoun, since, tooltipTitle, windowLabel,
} from './format.js'

describe('formatKwh', () => {
  it('groups thousands and keeps up to 2 decimals', () => {
    expect(formatKwh(12456.8)).toBe('12,456.8')
    expect(formatKwh(8.912)).toBe('8.91')
    expect(formatKwh(0)).toBe('0')
  })
  it('shows a dash for missing values', () => {
    expect(formatKwh(null)).toBe('—')
    expect(formatKwh(undefined)).toBe('—')
  })
})

describe('since', () => {
  const now = Date.parse('2026-10-06T10:00:00Z')
  it('rounds to the largest unit', () => {
    expect(since('2026-10-06T09:59:30Z', now)).toBe('<1 min')
    expect(since('2026-10-06T17:55:00+08:00', now)).toBe('5 min')
    expect(since('2026-10-06T07:00:00Z', now)).toBe('3 h')
    expect(since('2026-10-04T10:00:00Z', now)).toBe('2 d')
  })
  it('treats future timestamps as now', () => {
    expect(since('2026-10-06T10:05:00Z', now)).toBe('<1 min')
  })
})

describe('windowLabel', () => {
  it('formats each period from the server-local date part', () => {
    expect(windowLabel('hour', '2026-10-06T00:00:00+08:00', '2026-10-07T00:00:00+08:00'))
      .toBe('Tue, Oct 6 2026')
    expect(windowLabel('day', '2026-10-01T00:00:00+08:00', '2026-11-01T00:00:00+08:00'))
      .toBe('October 2026')
    expect(windowLabel('week', '2026-07-20T00:00:00+08:00', '2026-10-12T00:00:00+08:00'))
      .toBe('Jul 20 – Oct 11 2026')
    expect(windowLabel('month', '2026-01-01T00:00:00+08:00', '2027-01-01T00:00:00+08:00'))
      .toBe('2026')
    expect(windowLabel('year', '2024-01-01T00:00:00+08:00', '2027-01-01T00:00:00+08:00'))
      .toBe('All years')
  })
  it('shows both years when a week window crosses New Year', () => {
    expect(windowLabel('week', '2025-12-08T00:00:00+08:00', '2026-03-02T00:00:00+08:00'))
      .toBe('Dec 8 2025 – Mar 1 2026')
  })
})

describe('bucket labels', () => {
  it('formats axis labels', () => {
    expect(bucketLabel('hour', '2026-10-06T14:00:00+08:00')).toBe('14:00')
    expect(bucketLabel('day', '2026-10-06T00:00:00+08:00')).toBe('6')
    expect(bucketLabel('week', '2026-10-05T00:00:00+08:00')).toBe('Oct 5')
    expect(bucketLabel('month', '2026-10-01T00:00:00+08:00')).toBe('Oct')
    expect(bucketLabel('year', '2026-01-01T00:00:00+08:00')).toBe('2026')
  })
  it('formats tooltip titles', () => {
    expect(tooltipTitle('hour', '2026-10-06T14:00:00+08:00')).toBe('Oct 6, 14:00–15:00')
    expect(tooltipTitle('day', '2026-10-06T00:00:00+08:00')).toBe('Tue, Oct 6')
    expect(tooltipTitle('week', '2026-10-05T00:00:00+08:00')).toBe('Week of Oct 5')
    expect(tooltipTitle('month', '2026-10-01T00:00:00+08:00')).toBe('October 2026')
    expect(tooltipTitle('year', '2026-01-01T00:00:00+08:00')).toBe('2026')
  })
})

describe('misc', () => {
  it('periodNoun', () => {
    expect(periodNoun('hour')).toBe('this day')
    expect(periodNoun('day')).toBe('this month')
    expect(periodNoun('week')).toBe('these 12 weeks')
    expect(periodNoun('month')).toBe('this year')
    expect(periodNoun('year')).toBe('in total')
  })
  it('dateTime', () => {
    expect(dateTime('2026-10-06T10:58:12+08:00')).toBe('Oct 6, 10:58')
  })
})
