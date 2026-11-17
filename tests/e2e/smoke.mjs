// 歷史頁的冒煙測試（T-307、D-099、D-120）：只透過 HTTP 與瀏覽器操作 app，不 import 產品程式。
// 為什麼要有瀏覽器：「篩選無效時清空清單、停用匯出連結」是 history.html 裡的 JavaScript（htmx:beforeSwap），
// pytest 只看得到伺服器回的 422，抓不到畫面（M2 T-205 的 Verifier 就是這樣才發現兩個畫面變異）。
//
// 等待方式（pitfall #31）：不用 networkidle。送出前先在 body 掛好 htmx 事件的 Promise，送出後等「該次請求結束」
// （htmx:afterRequest；無效篩選不換畫面，只有這個事件），有效篩選再等換入後的 settle（htmx:afterSettle）。
import assert from "node:assert/strict";
import { chromium } from "playwright";

const BASE = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8765";
// 與 tests/e2e/seed.py 的常數一致（兩邊都是文字，沒有共用程式碼，刻意不 import 產品程式）
const ADMIN = "E2E管理員", ALICE = "E2E甲", BOB = "E2E乙", PASSWORD = "e2e-password";
const INVALID_MESSAGE = "請輸入有效的篩選條件"; // spec/appendix-b-fields.md；RPT-R23 的完整錯誤字串
const EXPORT_PATH = "/review/history/ordinary/export";

const browser = await chromium.launch();
const page = await (await browser.newContext({ locale: "zh-TW" })).newPage();
page.setDefaultTimeout(10_000);
let failed = false;

async function step(name, fn) {
  try { await fn(); console.log(`ok   - ${name}`); }
  catch (e) { failed = true; console.log(`FAIL - ${name}\n       ${String(e.message).split("\n").join("\n       ")}`); throw e; }
}

// 送出篩選表單，回傳時該次請求已結束、（有換畫面時）換入也已完成
async function submitFilter(fill, { swaps }) {
  await page.evaluate((swaps) => {
    const wait = (type) => new Promise((resolve) => document.body.addEventListener(type, resolve, { once: true }));
    window.__done = swaps ? Promise.all([wait("htmx:afterRequest"), wait("htmx:afterSettle")]) : wait("htmx:afterRequest");
  }, swaps);
  await fill();
  await page.getByRole("button", { name: "篩選" }).click();
  await page.evaluate(() => window.__done);
}

const rows = () => page.locator("#results tr[data-report-id]");
const exportLink = () => page.locator("#export-link");
const accountCells = async () => (await page.locator("#results td.account").allTextContents()).sort();

try {
  await step("管理員從登入頁登入（轉址到 /review；該頁由其他 ticket 實作，這裡不看內容）", async () => {
    await page.goto(`${BASE}/sign-in`);
    await Promise.all([page.waitForURL("**/sign-in?group=admin"), page.locator("#group").selectOption("admin")]);
    await page.locator("#name").selectOption(ADMIN);
    await page.locator("#password").fill(PASSWORD);
    await Promise.all([page.waitForURL("**/review"), page.getByRole("button", { name: "登入" }).click()]);
  });

  await step("基線：一般歷史列出兩張回報，匯出連結可用", async () => {
    await page.goto(`${BASE}/review/history/ordinary`);
    assert.deepEqual(await accountCells(), [ALICE, BOB].sort());
    assert.equal(await exportLink().getAttribute("href"), EXPORT_PATH);
    assert.equal(await exportLink().getAttribute("aria-disabled"), null);
  });

  await step("無效篩選（帳戶 Nobody）：顯示完整錯誤字串", async () => {
    await submitFilter(() => page.locator("input[name=account]").fill("Nobody"), { swaps: false });
    const box = page.locator("#filter-error");
    await box.waitFor({ state: "visible" });
    assert.equal(await box.textContent(), INVALID_MESSAGE);
  });

  await step("無效篩選：清單清空（沒有任何列、沒有表格、沒有「沒有符合條件」字樣、筆數清空）", async () => {
    assert.equal(await rows().count(), 0, "表單送出無效篩選後，清單仍有列");
    assert.equal(await page.locator("#results table").count(), 0);
    assert.equal(await page.locator("#results .empty").count(), 0);
    assert.equal((await page.locator("#results .count").textContent()).trim(), "");
  });

  await step("無效篩選：「匯出 Excel」停用（沒有 href、沒有 download、aria-disabled、點不到）", async () => {
    const link = exportLink();
    assert.equal(await link.getAttribute("href"), null, "停用的匯出連結不可保留 href（會指向舊篩選）");
    assert.equal(await link.getAttribute("download"), null);
    assert.equal(await link.getAttribute("aria-disabled"), "true");
    await assert.rejects(() => link.click({ timeout: 1000 }), "停用的匯出連結不應該點得到");
    assert.equal(await link.textContent(), "匯出 Excel");
  });

  await step("有效篩選（帳戶 E2E乙）：錯誤訊息消失、清單恢復、匯出連結恢復並帶著新篩選", async () => {
    await submitFilter(() => page.locator("input[name=account]").fill(BOB), { swaps: true });
    assert.equal(await page.locator("#filter-error").isHidden(), true);
    assert.deepEqual(await accountCells(), [BOB]);
    const href = await exportLink().getAttribute("href");
    assert.equal(href, `${EXPORT_PATH}?account=${encodeURIComponent(BOB)}`);
    assert.equal(await exportLink().getAttribute("aria-disabled"), null);
  });
} catch (e) {
  // 失敗時把畫面上的狀態印出來，CI 的 log 就能看出是哪一塊壞了
  console.log("--- 失敗時的 #filter-error 與 #results ---");
  console.log(await page.locator("#filter-error").evaluate((el) => `hidden=${el.hidden} text=${JSON.stringify(el.textContent)}`).catch(() => "(取不到)"));
  console.log(await page.locator("#results").evaluate((el) => el.outerHTML.replace(/\s+/g, " ").slice(0, 1200)).catch(() => "(取不到)"));
  if (process.env.E2E_FAILURE_SHOT) { await page.screenshot({ path: process.env.E2E_FAILURE_SHOT, fullPage: true }); }
} finally {
  await browser.close();
}
process.exit(failed ? 1 : 0);
