/**
 * E2E smoke dell'app online (frontend unico, tutto via backend).
 * Copre l'avvio delle pagine chiave e il flusso reale di registrazione/login
 * contro il backend FastAPI (vedi webServer in playwright.config.js).
 */
import { test, expect } from '@playwright/test';

const TOKEN_KEY = 'mull2five-jwt-v1';
const uniqueEmail = () => `e2e_${Date.now()}_${Math.floor(Math.random() * 1e4)}@test.it`;

test.beforeEach(async ({ page }) => {
  await page.goto('/index.html');
  await page.evaluate(() => localStorage.clear());
});

test('home pubblica si carica e mostra brand + rail eventi', async ({ page }) => {
  await page.goto('/index.html');
  // Dal rebrand il marchio è un'immagine: il nome sta nell'alt, non nel testo.
  await expect(page.locator('.brand img')).toHaveAttribute('alt', 'Mull2Five');
  await expect(page.locator('h1')).toContainText('Scopri Magic');
  // La rail la riempie il backend: finito il caricamento c'è una scheda evento
  // (con i posti liberi) o il messaggio di lista vuota, mai un errore.
  await expect(page.locator('#eventsRail')).toContainText(/Nessun evento in questa selezione|posti/);
});

test('login mostra i tab Accedi / Registrati', async ({ page }) => {
  await page.goto('/login.html');
  await expect(page.locator('#tabLogin')).toBeVisible();
  await expect(page.locator('#tabRegister')).toBeVisible();
  await page.click('#tabRegister');
  await expect(page.locator('#formRegister')).toBeVisible();
});

test('registrazione → redirect a "Le mie iscrizioni" con token salvato', async ({ page }) => {
  const email = uniqueEmail();
  await page.goto('/login.html');
  await page.click('#tabRegister');
  await page.fill('#regName', 'E2E Tester');
  await page.fill('#regEmail', email);
  await page.fill('#regPassword', 'password123');
  await page.fill('#regConfirm', 'password123');
  await page.click('#formRegister button[type="submit"]');

  await page.waitForURL('**/my-registrations.html', { timeout: 15_000 });
  await expect(page.locator('h1')).toContainText('Le mie iscrizioni');
  const token = await page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY);
  expect(token).toBeTruthy();
});

test('registrazione come Organizzatore → back-office accessibile', async ({ page }) => {
  const email = uniqueEmail();
  await page.goto('/login.html');
  await page.click('#tabRegister');
  await page.fill('#regName', 'E2E Organizer');
  await page.fill('#regEmail', email);
  await page.fill('#regPassword', 'password123');
  await page.fill('#regConfirm', 'password123');
  await page.selectOption('#regRole', 'organizer');
  await page.click('#formRegister button[type="submit"]');

  // Un organizzatore viene portato direttamente al back-office.
  await page.waitForURL('**/organizer.html', { timeout: 15_000 });
  // Si apre sulla lista dei suoi eventi, vuota per un account appena creato.
  await expect(page.locator('.bo-nav-item[data-section="eventi"]')).toHaveClass(/active/);
  await expect(page.locator('#boNew')).toBeVisible();
  await expect(page.locator('#panel')).toContainText('Nessun evento in corso');
});

test('login con credenziali appena registrate', async ({ page }) => {
  const email = uniqueEmail();
  // registra
  await page.goto('/login.html');
  await page.click('#tabRegister');
  await page.fill('#regName', 'E2E Login');
  await page.fill('#regEmail', email);
  await page.fill('#regPassword', 'password123');
  await page.fill('#regConfirm', 'password123');
  await page.click('#formRegister button[type="submit"]');
  await page.waitForURL('**/my-registrations.html', { timeout: 15_000 });

  // logout (svuota token) e rientra dal login
  await page.evaluate((k) => localStorage.removeItem(k), TOKEN_KEY);
  await page.goto('/login.html');
  await page.fill('#loginEmail', email);
  await page.fill('#loginPassword', 'password123');
  await page.click('#formLogin button[type="submit"]');
  await page.waitForURL('**/my-registrations.html', { timeout: 15_000 });
  await expect(page.locator('h1')).toContainText('Le mie iscrizioni');
});
