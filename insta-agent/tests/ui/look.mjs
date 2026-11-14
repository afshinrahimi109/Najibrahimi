import {start, BASE, ASSETS, out, sleep} from './lib.mjs';
const t = await start();
const {page} = t;
try {
  await page.goto(BASE + '/', {waitUntil: 'networkidle0'});
  await page.waitForSelector('#nav button[data-tab="home"]', {timeout: 15000});
  await t.tab('content');
  await page.click('#fab'); await sleep(400);
  await page.click('.sheet .kinds button[data-kind="carousel"]');
  await (await page.$('.sheet input[type=file]')).uploadFile(ASSETS + '/wide.png');
  await page.waitForSelector('.sheet .mitem img', {timeout: 15000});
  await (await page.$('.sheet input[type=file]')).uploadFile(ASSETS + '/wide.png');
  await page.waitForFunction(() => document.querySelectorAll('.sheet .mitem img').length === 2, {timeout: 15000});
  await t.type('textarea[aria-label="کپشن"]', 'منوی تازه ☕️ ورق بزنید\n#کافه');
  await t.shot('70-composer-carousel');
  await t.inTop(s => s.querySelector('button[data-seg="later"]').click()); await sleep(900);
  await t.inTop(s => { s.querySelector('details.box summary').click(); s.querySelector('.body').scrollTop = 99999; }); await sleep(300);
  await t.shot('71-composer-bottom');
  await t.closeSheet();
  await t.tab('agent');
  await page.evaluate(() => window.scrollTo(0, 99999)); await sleep(300);
  await t.shot('72-agent-bottom');
  await page.evaluate(() => { document.querySelector('details.box summary').click(); window.scrollTo(0, 99999); }); await sleep(300);
  await t.shot('73-agent-brakes');
} catch (e) { t.fail(); console.log('EXCEPTION', e.message); await page.screenshot({path: out + '/99-exception.png'}); }
await t.finish('LOOK');
