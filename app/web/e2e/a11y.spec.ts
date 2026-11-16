import AxeBuilder from '@axe-core/playwright'
import {expect, test} from '@playwright/test'

// Real Chromium rendering, so colour contrast is actually evaluated (jsdom
// cannot compute it). Serious and critical WCAG violations fail the build.
for (const [name, path] of [
  ['exploration', '/'],
  ['previsions', '/?tab=previsions'],
  ['methode', '/?tab=methode'],
] as const) {
  test(`no serious or critical axe violations — ${name}`, async ({page}) => {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    const results = await new AxeBuilder({page})
      // The embedded architecture viewer ships its own UI and its own checks;
      // page-level WCAG is asserted on our own markup.
      .exclude('iframe')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    const blocking = results.violations.filter(
      violation =>
        violation.impact === 'serious' || violation.impact === 'critical',
    )
    expect(
      blocking.map(
        violation =>
          `${violation.id} (${violation.impact}): ${violation.help} :: ${violation.nodes.map(n => n.target.join(' ')).join(' | ')}`,
      ),
    ).toEqual([])
  })
}
