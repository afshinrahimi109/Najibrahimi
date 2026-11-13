// First run on a real setup: login with the key, connect a page with a token, settings that touch the network, disconnect.
// Run with:  python3 serve.py connect.mjs sim
import {start, BASE, KEY, TOKEN, out, sleep} from './lib.mjs';
const t = await start();
const {page} = t;
const loginBox = 'input[aria-label="کد ورود"]', tokenBox = 'textarea[aria-label="توکن"]';
try {
  // 1. nothing is shown without the key
  await page.goto(BASE + '/', {waitUntil: 'networkidle0'});
  await page.waitForSelector(loginBox, {timeout: 15000});
  t.check('login screen first', (await page.$('#nav.hide')) !== null || (await page.$eval('#nav', e => getComputedStyle(e).display === 'none')));
  const anon = await page.evaluate(() => fetch('/api/posts').then(r => r.status));
  t.check('API closed without login', anon === 401, anon);
  await t.shot('80-login');
  await t.type(loginBox, 'AAAAA-BBBBB');
  await t.clickText('ورود');
  t.check('wrong key is explained', await t.waitText('کد ورود درست نیست', 8000));
  t.check('still on the login screen', (await page.$(loginBox)) !== null);
  await t.type(loginBox, KEY.toLowerCase().replace('-', ' '));          // typed in lower case, with a space
  await t.clickText('ورود');
  await page.waitForSelector(tokenBox, {timeout: 15000});
  t.check('after login the connect guide is shown', await t.waitText('توکن', 5000));
  await t.shot('81-connect');

  // 2. connecting
  await t.type(tokenBox, 'IGAA' + 'x'.repeat(40));
  t.check('the wrong-key message is gone after login', (await page.$('#toasts .toast')) === null);
  await t.clickText('اتصال به پیج');
  await page.waitForSelector('#toasts .toast.bad', {timeout: 8000});
  const why = await page.$eval('#toasts .toast.bad', e => e.textContent);
  t.check('wrong token is explained in Persian', /توکن/.test(why) && !/OAuth|Exception|undefined/.test(why), why);
  t.check('still on the connect guide', (await page.$(tokenBox)) !== null);
  await t.shot('82-bad-token');
  await t.type(tokenBox, TOKEN);
  await t.clickText('اتصال به پیج');
  await page.waitForSelector('#nav button[data-tab="home"]', {visible: true, timeout: 20000});
  t.check('page connected', (await page.$eval('#top h1', e => e.textContent)) === '@demo.cafe');
  t.check('token is not kept in the page', await page.evaluate(tok => !document.documentElement.innerHTML.includes(tok) && !JSON.stringify(localStorage).includes(tok), TOKEN));
  await sleep(1500);
  await t.shot('83-home-first');
  const st = await t.api('/api/status');
  t.check('nothing automatic is on at first', Object.values(st.auto).every(v => v === false) && st.counts.auto_today === 0, st.auto);
  t.check('status never carries the token', !JSON.stringify(st).includes(TOKEN));

  // 3. a reload keeps the session; the link with ?k= logs a new browser in
  await page.reload({waitUntil: 'networkidle0'});
  await page.waitForSelector('#nav button[data-tab="home"]', {visible: true, timeout: 15000});
  t.check('reload keeps the session', (await page.$(loginBox)) === null);
  const cdp = await page.createCDPSession();
  await cdp.send('Network.clearBrowserCookies');
  await page.goto(BASE + '/', {waitUntil: 'networkidle0'});
  await page.waitForSelector(loginBox, {timeout: 15000});
  t.check('without the cookie: login again', true);
  await page.goto(BASE + '/?k=' + KEY, {waitUntil: 'networkidle0'});
  await page.waitForSelector('#nav button[data-tab="home"]', {visible: true, timeout: 15000});
  t.check('the printed link logs in', !page.url().includes('k='), page.url());

  // 4. settings: a wrong proxy is refused, a right one is saved; Telegram test without a token is explained
  await t.tab('agent');
  await page.click('#open-settings');
  await page.waitForSelector('.sheet details[data-sec="network"]', {timeout: 8000});
  await page.evaluate(() => document.querySelector('.sheet details[data-sec="network"] summary').click());
  await page.evaluate(() => { const d = document.querySelector('.sheet details[data-sec="network"]'); const i = d.querySelector('input'); i.value = 'socks5://127.0.0.1:1080'; d.querySelector('.btn.pri').click(); });
  t.check('SOCKS proxy is refused with a reason', await t.waitText('فقط پروکسی HTTP', 8000));
  await t.shot('84-settings-network');
  await sleep(300);
  t.check('nothing was saved', (await t.api('/api/settings')).network.proxy === '');
  await page.evaluate(() => document.querySelector('.sheet details[data-sec="telegram"] summary').click());
  await sleep(200);
  await t.clickText('آزمایش');
  t.check('telegram test without a token is explained', await page.waitForFunction(() => !!document.querySelector('#toasts .toast.bad'), {timeout: 8000}).then(() => true, () => false));
  await page.evaluate(() => document.querySelector('.sheet .body').scrollTop = 99999);
  await t.shot('85-settings-bottom');

  await t.closeSheet();

  // 5. disconnect asks first; then back to the guide, and the token is gone
  await t.clickText('قطع اتصال');
  await sleep(400);
  t.check('disconnect asks first', (await t.sheets()) === 1 && (await t.api('/api/status')).connected === true);
  await t.shot('86-disconnect-confirm');
  await t.clickText('نه');
  await sleep(400);
  t.check('"no" keeps the page connected', (await t.api('/api/status')).connected === true && (await t.sheets()) === 0);
  await t.clickText('قطع اتصال');
  await sleep(400);
  await t.clickText('قطع اتصال');
  await page.waitForSelector(tokenBox, {timeout: 15000});
  t.check('disconnected: connect guide again', true);
  t.check('status says so', (await t.api('/api/status')).connected === false);
  t.check('no script from hostile content ran', (await page.evaluate(() => window.__xss)) === undefined);

  // 6. logout
  const left = await page.evaluate(() => fetch('/api/logout', {method: 'POST', headers: {'X-IA': '1'}}).then(r => r.status));
  await page.reload({waitUntil: 'networkidle0'});
  await page.waitForSelector(loginBox, {timeout: 15000});
  t.check('logout ends the session', left === 200);
} catch (e) {
  t.fail();
  console.log('EXCEPTION', e.message);
  await page.screenshot({path: out + '/99-exception.png'});
}
await t.finish('CONNECT FLOW', /status of 401|status of 502|status of 400/);
