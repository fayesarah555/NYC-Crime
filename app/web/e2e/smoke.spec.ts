import {expect, test} from '@playwright/test'

test('loads with reconciled KPIs and renders the three tabs', async ({page}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', {level: 1})).toContainText(
    'Criminalité dans les parcs de New York',
  )
  await expect(page.getByText('12 544', {exact: false}).first()).toBeVisible()
  await expect(page.getByText('792', {exact: false}).first()).toBeVisible()
  for (const tab of ['Exploration', 'Prévisions', 'Méthode']) {
    await expect(page.getByRole('tab', {name: tab})).toBeVisible()
  }
  await page.screenshot({path: 'e2e/screenshots/exploration.png', fullPage: true})
})

test('borough and search filters move the KPIs together', async ({page}) => {
  await page.goto('/')
  await page.getByRole('combobox').first().click()
  await page.getByRole('option', {name: 'MANHATTAN', exact: true}).click()
  await expect(page.getByText('4 132', {exact: false}).first()).toBeVisible()

  const search = page.getByPlaceholder('Ex. : central, pelham')
  await search.fill('central')
  await expect(page.getByText(/1 parc dans la sélection/)).toBeVisible()
})

test('forecast tab shows the selected model, interval level and caveat', async ({
  page,
}) => {
  await page.goto('/?tab=previsions')
  await expect(page.getByText('SEASONAL_NAIVE', {exact: false}).first()).toBeVisible()
  await expect(page.getByText(/Intervalle à 95 %/)).toBeVisible()
  await expect(page.getByText(/Central Park/).first()).toBeVisible()
  await page.screenshot({path: 'e2e/screenshots/previsions.png', fullPage: true})
})

test('method tab links the sources and shows freshness', async ({page}) => {
  await page.goto('/?tab=methode')
  await expect(page.getByRole('link', {name: /NYPD/}).first()).toBeVisible()
  await expect(page.getByText(/Export généré le/)).toBeVisible()
  await page.screenshot({path: 'e2e/screenshots/methode.png', fullPage: true})
})
