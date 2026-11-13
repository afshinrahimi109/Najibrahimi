// Puts several screenshots side by side in one picture, for a quick look:  node montage.mjs out.png a.png b.png …
import chromium from '@sparticuz/chromium';
import puppeteer from 'puppeteer-core';
import path from 'node:path';
import fs from 'node:fs';
const [target, ...files] = process.argv.slice(2);
const own = process.env.CHROME_PATH;
const browser = await puppeteer.launch(own ? {executablePath: own, headless: true, args: ['--no-sandbox']}
  : {args: [...chromium.args, '--no-sandbox', '--disable-gpu'], executablePath: await chromium.executablePath(), headless: 'shell'});
const page = await browser.newPage();
const w = Number(process.env.TILE || 390), h = Math.round(w * 844 / 390);
await page.setViewport({width: w * files.length, height: h, deviceScaleFactor: 1});
const data = f => 'data:image/png;base64,' + fs.readFileSync(path.resolve(f)).toString('base64');
await page.setContent('<body style="margin:0;display:flex;background:#888">' + files.map(f => `<img src="${data(f)}" style="width:${w}px;height:${h}px;display:block">`).join('') + '</body>', {waitUntil: 'load'});
await page.screenshot({path: target});
await browser.close();
