// Small helpers shared by the browser scripts: a phone-sized page, text clicks, checks, and a problem log.
import chromium from '@sparticuz/chromium';
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
export const BASE = process.env.BASE, KEY = process.env.KEY, TOKEN = process.env.TOKEN;
export const ASSETS = process.env.ASSETS || '.', out = process.env.SHOTS || './shots';
fs.mkdirSync(out, {recursive: true});
export const sleep = ms => new Promise(r => setTimeout(r, ms));
export async function start(opts = {}) {
  const own = process.env.CHROME_PATH;                 // an installed browser, if you have one
  const browser = await puppeteer.launch(own ? {executablePath: own, headless: true, args: ['--no-sandbox']}
    : {args: [...chromium.args, '--no-sandbox', '--disable-gpu'], executablePath: await chromium.executablePath(), headless: 'shell'});
  const page = await browser.newPage();
  await page.setViewport({width: opts.width || 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true});
  if (opts.dark) await page.emulateMediaFeatures([{name: 'prefers-color-scheme', value: 'dark'}]);
  const problems = [];
  page.on('console', m => { if (['error', 'warning'].includes(m.type())) problems.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  page.on('requestfailed', r => problems.push('requestfailed: ' + r.url() + ' ' + (r.failure() || {}).errorText));
  let failed = 0;
  const t = {
    browser, page, problems,
    check(name, ok, extra) { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  ' + (extra === undefined ? '' : JSON.stringify(extra)))); if (!ok) failed++; },
    async shot(name) { await sleep(350); await page.screenshot({path: `${out}/${name}.png`}); },
    // click the shortest visible element containing the text, inside the top sheet if one is open
    async clickText(text, tag = 'button, a, summary') {
      const ok = await page.evaluate((text, tag) => {
        const sheets = [...document.querySelectorAll('.sheet')];
        const root = sheets.length ? sheets[sheets.length - 1] : document.body;
        const els = [...root.querySelectorAll(tag)].filter(e => e.offsetParent !== null && e.textContent.replace(/\s+/g, ' ').includes(text));
        if (!els.length) return false;
        els.sort((a, b) => a.textContent.length - b.textContent.length);
        els[0].click(); return true;
      }, text, tag);
      if (!ok) throw new Error('nothing to click with text: ' + text);
      await sleep(250);
    },
    async waitText(text, timeout = 15000) { try { await page.waitForFunction(x => document.body.innerText.includes(x), {timeout}, text); return true; } catch (e) { return false; } },
    sheets: () => page.evaluate(() => document.querySelectorAll('.sheet').length),
    async closeSheet() { await page.evaluate(() => { const s = [...document.querySelectorAll('.sheet')].pop(); if (s) s.querySelector('.head .iconbtn').click(); }); await sleep(250); },
    async tab(name) { await page.click(`#nav button[data-tab="${name}"]`); await sleep(900); },
    api: path => page.evaluate(p => fetch(p).then(r => r.json()), path),
    async type(selector, text) {
      await page.evaluate((selector, text) => {
        const sheets = [...document.querySelectorAll('.sheet')];
        const root = sheets.length ? sheets[sheets.length - 1] : document.body;
        const el = root.querySelector(selector);
        if (!el) throw new Error('no element: ' + selector);
        el.focus(); el.value = text; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); el.blur();
      }, selector, text);
    },
    inTop: (fn, ...args) => page.evaluate(new Function('...a', 'const s=[...document.querySelectorAll(".sheet")].pop(); return (' + fn.toString() + ')(s, ...a)'), ...args),
    async finish(label, ignore) {
      const real = problems.filter(p => !(ignore && ignore.test(p)));
      console.log('PROBLEMS', JSON.stringify(real, null, 1));
      if (real.length) failed++;
      await browser.close();
      console.log(failed ? `${label}: ${failed} FAILED` : `${label}: ALL PASSED`);
      process.exit(failed ? 1 : 0);
    },
    fail() { failed++; },
  };
  return t;
}
