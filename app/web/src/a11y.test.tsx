import {describe, expect, it} from 'vitest'
import {render} from '@testing-library/react'
import axe from 'axe-core'
import Dashboard from './pages/Dashboard'

// jsdom cannot judge colour contrast, so that rule is disabled; every other
// serious or critical WCAG violation fails the suite.
describe('accessibility', () => {
  it('has no serious or critical axe violations on the dashboard', async () => {
    const {container} = render(<Dashboard />)
    const results = await axe.run(container, {
      rules: {
        'color-contrast': {enabled: false},
      },
    })
    const blocking = results.violations.filter(
      violation =>
        violation.impact === 'serious' || violation.impact === 'critical',
    )
    expect(blocking.map(violation => `${violation.id}: ${violation.help}`)).toEqual([])
  }, 30_000)
})
