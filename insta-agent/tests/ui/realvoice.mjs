// The narrator on the device, for real: its files are downloaded the way a phone gets them, the Persian voice reads
// every scene of a reel in this browser, and the sound ends up inside the MP4.
//     Run with:  python3 serve.py realvoice.mjs real        (network needed: about 85 MB, once per run)
import {start, BASE, out, sleep} from './lib.mjs';
import fs from 'node:fs';
import path from 'node:path';
const t = await start();
const {page} = t;
const note = (title, text) => { console.log(title + ': ' + text); if (process.env.GITHUB_ACTIONS) console.log('::notice title=' + title + '::' + String(text).replace(/\r?\n/g, ' ')); };
const card = () => t.inTop(s => { const c = s.querySelector('[data-voice]'); return c && {mode: c.dataset.voice, text: c.textContent, pack: (c.querySelector('[data-pack]') || {dataset: {}}).dataset.pack || '',
  says: [...c.querySelectorAll('textarea[aria-label^="متن گوینده"]')].map(e => e.value), speaker: (c.querySelector('select[aria-label="گوینده"]') || {}).value,
  secs: [...c.querySelectorAll('label.f')].map(e => (e.textContent.match(/\(([۰-۹٫]+) ثانیه\)/) || [])[1]).filter(Boolean).map(x => parseFloat(x.replace(/[۰-۹]/g, d => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)).replace('٫', '.')))}; });
try {
  await page.goto(BASE + '/', {waitUntil: 'networkidle0'});
  await page.waitForSelector('[data-manual]', {timeout: 15000});
  await page.click('[data-manual]');
  await page.waitForSelector('#nav button[data-tab="home"]', {visible: true, timeout: 15000});
  const st = await t.api('/api/status');
  t.check('without a key the narrator is the one on the device', st.studio.speaker === 'device' && st.studio.voice === false, st.studio);

  // a reel; the narrator is not on this device yet, so it comes out silent and offers the download
  await t.type('textarea[aria-label="ایده"]', 'تخفیف ۲۰٪ لاتهٔ پاییزی تا آخر هفته');
  await page.click('[data-make="reel"]');
  await page.waitForSelector('.sheet canvas.stage.tall', {timeout: 180000});
  await sleep(600);
  const before = await card();
  const fresh = st.studio.pack.state !== 'ready';
  if (fresh) {
    t.check('the silent reel offers the Persian narrator', before.mode === 'none' && before.text.includes('گویندهٔ فارسی را دانلود کن') && ['none', 'failed'].includes(before.pack), before);
    await t.shot('120-offer');
    const t0 = Date.now();
    await page.click('.sheet [data-pack-do="get"]');
    await page.waitForFunction(() => document.querySelector('.sheet [data-pack="loading"]') || document.querySelector('.sheet [data-reading]') || document.querySelector('.sheet [data-voice="ai"]'), {timeout: 20000});
    await t.shot('121-downloading');
    let last = '';
    for (;;) {                                         // the download, then the first reading
      const pk = await t.api('/api/studio/pack');
      if (pk.state !== last) { note('narrator pack', pk.state + ' ' + pk.pct + '% after ' + Math.round((Date.now() - t0) / 1000) + ' s' + (pk.why ? ' — ' + pk.why : '')); last = pk.state; }
      if (pk.state === 'ready' || pk.state === 'failed' || pk.state === 'none') break;
      if (Date.now() - t0 > 25 * 60000) break;
      await sleep(2000);
    }
    const pk = await t.api('/api/studio/pack');
    t.check('the narrator was downloaded and every file checked', pk.state === 'ready' && pk.pct === 100, pk);
    if (pk.state !== 'ready') throw new Error('no narrator: ' + pk.why);
    note('narrator pack', 'ready after ' + Math.round((Date.now() - t0) / 1000) + ' s');
  } else {
    t.check('the narrator is on this device already', before.mode === 'ai', before);
  }
  const t1 = Date.now();
  await page.waitForFunction(() => { const c = document.querySelector('.sheet [data-voice]'); return c && c.dataset.voice === 'ai'; }, {timeout: 600000});
  await sleep(500);
  const told = await card();
  note('narrator', 'read ' + told.secs.length + ' scenes (' + told.secs.join(' + ') + ' s of speech) within ' + Math.round((Date.now() - t1) / 1000) + ' s of the download');
  t.check('every scene was read by the narrator on the device', told.mode === 'ai' && told.speaker === 'device' && told.says.length === 4 && told.secs.length === 4 && told.secs.every(x => x > 0.8 && x < 30), told);
  await t.shot('122-narrated');
  await t.inTop(s => { s.querySelector('[data-voice]').scrollIntoView(); });
  await t.shot('123-lines');

  // one line is changed: only that one is read again, this time with the engine already loaded
  const line = 'قهوهٔ ما هر روز صبح تازه دم می‌شود؛ ساعت ۸ تا ۲۳ منتظر شما هستیم.';
  await t.type('textarea[aria-label="متن گوینده 2"]', line);
  const t2 = Date.now();
  await page.click('.sheet [data-studio-done]');
  await page.waitForFunction(() => !document.querySelector('.sheet canvas.stage') && document.querySelector('.sheet .mitem .tag'), {timeout: 600000});
  const m = await page.evaluate(() => S.made);
  note('reel', JSON.stringify(m) + ' made in ' + Math.round((Date.now() - t2) / 1000) + ' s');
  t.check('the reel is an MP4 with the narration in it', m.type === 'video/mp4' && m.voice === 'ai' && ['aac', 'opus'].includes(m.sound) && m.seconds > 12 && m.seconds < 90, m);
  const b64 = await page.evaluate(async id => { const b = await (await fetch('/api/file/' + id)).arrayBuffer(); let s = ''; const u = new Uint8Array(b); for (let i = 0; i < u.length; i += 32768) s += String.fromCharCode.apply(null, u.subarray(i, i + 32768)); return btoa(s); }, m.file);
  fs.writeFileSync(path.join(out, 'made-reel-persian.mp4'), Buffer.from(b64, 'base64'));
  fs.writeFileSync(path.join(out, 'made-real.json'), JSON.stringify({'made-reel-persian.mp4': Object.assign({w: m.way === '720' ? 720 : 1080, h: m.way === '720' ? 1280 : 1920, speech: 4, real: true,
    says: [told.says[0], line, told.says[2], told.says[3]]}, m)}, null, 1));
  await t.shot('124-ready');
} catch (e) {
  console.log('EXCEPTION', e);
  t.check('the script ran to its end', false, String(e));
  try { await t.shot('129-where-it-stopped'); } catch (x) { /* no page */ }
}
await t.finish('REAL VOICE', /status of 4\d\d|\/api\/file\/\w+(#t=0\.1)? net::ERR_ABORTED/);
