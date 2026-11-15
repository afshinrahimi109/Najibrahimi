// No page connected: the owner chooses to post by hand, lets the studio make a picture and a reel from an idea,
// and takes file and caption out of the panel.     Run with:  python3 serve.py byhand.mjs hand
import {start, BASE, AI_KEY, ASSETS, out, sleep} from './lib.mjs';
import fs from 'node:fs';
import path from 'node:path';
const t = await start();
const {page, browser} = t;
const downloads = path.join(out, 'downloads');
fs.rmSync(downloads, {recursive: true, force: true});
fs.mkdirSync(downloads, {recursive: true});
const idea = 'تخفیف ۲۰٪ لاتهٔ پاییزی <b onmouseover="window.__xss=7">تا آخر هفته</b>';
const stageInk = () => page.evaluate(() => {          // a rough fingerprint of what is drawn on the studio's canvas
  const cv = document.querySelector('.sheet canvas.stage'), d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
  let sum = 0, seen = new Set();
  for (let i = 0; i < d.length; i += 4 * 997) { sum = (sum * 31 + d[i] + d[i + 1] * 3 + d[i + 2] * 7) % 1000000007; seen.add(d[i] >> 4 << 8 | d[i + 1] >> 4 << 4 | d[i + 2] >> 4); }
  return {sum, colours: seen.size, w: cv.width, h: cv.height};
});
const sounds = {};                                    // file name → what the panel says about the reel it made (read by check_made.py)
const voiceCalls = [];                                // what the narrator was asked to read, call by call
page.on('request', r => { if (r.method() === 'POST' && r.url().endsWith('/api/studio/voice')) voiceCalls.push(JSON.parse(r.postData())); });
const speechSeconds = text => Math.min(20, Math.max(0.6, Math.floor(100 * (0.35 + 0.07 * text.length)) / 100));     // the simulator's speaker
const reelSeconds = says => says.reduce((sum, x) => sum + Math.max(3.2, speechSeconds(x) + 0.95), 0) + 0.2;
const voiceCard = () => t.inTop(s => { const c = s.querySelector('[data-voice]'); return c && {mode: c.dataset.voice, text: c.textContent, ai: !!c.querySelector('[data-voice-do="ai"]'), play: !!c.querySelector('[data-voice-do="play"]'),
  says: [...c.querySelectorAll('textarea[aria-label^="متن گوینده"]')].map(e => e.value), speaker: (c.querySelector('select[aria-label="گوینده"]') || {}).value,
  pack: (c.querySelector('[data-pack]') || {dataset: {}}).dataset.pack || '', get: !!c.querySelector('[data-pack-do="get"]'),
  secs: [...c.querySelectorAll('label.f')].map(e => (e.textContent.match(/\(([۰-۹٫]+) ثانیه\)/) || [])[1]).filter(Boolean).map(x => parseFloat(x.replace(/[۰-۹]/g, d => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)).replace('٫', '.')))}; });
const saveFile = async (id, name) => {
  const b64 = await page.evaluate(async id => { const b = await (await fetch('/api/file/' + id)).arrayBuffer(); let s = ''; const u = new Uint8Array(b); for (let i = 0; i < u.length; i += 32768) s += String.fromCharCode.apply(null, u.subarray(i, i + 32768)); return btoa(s); }, id);
  fs.writeFileSync(path.join(out, name), Buffer.from(b64, 'base64'));
  return fs.statSync(path.join(out, name)).size;
};
try {
  await browser.defaultBrowserContext().overridePermissions(BASE, ['clipboard-read', 'clipboard-write']);
  const cdp = await page.createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: downloads});
  await page.evaluateOnNewDocument(() => {            // a phone has a share sheet; this browser has not, so one is put in its place
    navigator.canShare = d => !!(d && d.files && d.files.length);
    navigator.share = async d => { window.__shared = d.files.map(f => [f.name, f.type, f.size]); };
  });

  // 1. two ways to start; without a token the owner posts by hand
  await page.goto(BASE + '/', {waitUntil: 'networkidle0'});
  await page.waitForSelector('[data-manual]', {timeout: 15000});
  t.check('the start screen offers both ways', (await page.$('textarea[aria-label="توکن"]')) !== null && await t.waitText('بدون اتصال', 3000));
  const face = await page.evaluate(async () => { await document.fonts.load('800 40px Vazirmatn'); return document.fonts.check('800 40px Vazirmatn'); });
  t.check('the Persian typeface is loaded from the agent itself', face);
  await t.shot('90-start');
  await page.click('[data-manual]');
  await page.waitForSelector('#nav button[data-tab="home"]', {visible: true, timeout: 15000});
  const tabs = await page.$$eval('#nav button', els => els.map(e => e.dataset.tab));
  t.check('only the tabs that work without a page', JSON.stringify(tabs) === '["home","content","agent"]', tabs);
  t.check('the header says who posts', (await page.$eval('#top', e => e.textContent)).includes('انتشار با خودت'));
  const st0 = await t.api('/api/status');
  t.check('status: not connected, by hand', st0.connected === false && st0.manual === true);
  t.check('without a key the narrator would be the one on the device, which is not there yet', st0.studio.voice === false && st0.studio.speaker === 'device' && st0.studio.pack.state === 'none', st0.studio);
  const hint = await page.$eval('[data-home-voice]', e => ({text: e.textContent, get: !!e.querySelector('[data-pack-do="get"]')}));
  t.check('the home screen offers the free Persian narrator', hint.get && hint.text.includes('ویدیو با صدای گوینده') && hint.text.includes('۸۵ مگابایت') && hint.text.includes('بدون کلید'), hint);
  await sleep(600);
  await t.shot('91-home');

  // 2. a picture out of one idea
  await t.type('textarea[aria-label="ایده"]', idea);
  await page.click('[data-make="image"]');
  await page.waitForSelector('.sheet canvas.stage', {timeout: 60000});
  await sleep(500);
  const first = await stageInk();
  t.check('the picture is drawn at feed size', first.w === 1080 && first.h === 1350 && first.colours > 20, first);
  t.check('it was made from an AI picture', (await page.$eval('.sheet [data-pics]', e => e.dataset.pics)) === '1');
  const cap = await page.$eval('.sheet [data-caption]', e => e.textContent);
  t.check('caption and hashtags are written', cap.includes('لاتهٔ پاییزی') && /#\S+/.test(cap), cap);
  const head = await page.$eval('.sheet input[aria-label="نوشتهٔ روی تصویر"]', e => e.value);
  t.check('a headline is proposed', head.length > 3, head);
  await t.shot('92-studio-picture');
  await t.type('input[aria-label="نوشتهٔ روی تصویر"]', 'فقط همین هفته ☕️');
  await sleep(200);
  const second = await stageInk();
  t.check('changing the words redraws the picture', second.sum !== first.sum);
  await page.click('.sheet [data-look]'); await sleep(200);
  const third = await stageInk();
  t.check('another layout is one tap away', third.sum !== second.sum);
  await t.shot('92b-studio-layout');
  await page.click('.sheet [data-studio-done]');
  await page.waitForSelector('.sheet .kinds', {timeout: 20000});
  await sleep(500);

  // 3. the composer speaks of posting by hand
  const comp = await t.inTop(s => ({tag: (s.querySelector('.mitem .tag') || {}).textContent, caption: s.querySelector('textarea[aria-label="کپشن"]').value,
    go: s.querySelector('[data-go]').textContent, link: !!s.querySelector('[data-add="url"]'), more: s.textContent.includes('گزینه‌های بیشتر'), kind: s.querySelector('.kinds .on').dataset.kind}));
  t.check('the picture and the caption arrive in the composer', comp.tag === 'عکس' && comp.caption.includes('لاتهٔ پاییزی') && comp.kind === 'image', comp);
  t.check('no API-only choices without a page', comp.go.includes('آماده کن') && !comp.link && !comp.more, comp);
  await t.shot('93-composer');
  await page.click('.sheet [data-go]');
  await page.waitForSelector('.sheet [data-kit="box"]', {timeout: 15000});
  await page.waitForFunction(() => { const i = document.querySelector('.sheet img.big'); return i && i.complete && i.naturalWidth > 0; }, {timeout: 15000});
  const img = await page.$eval('.sheet img.big', e => [e.naturalWidth, e.naturalHeight]);
  t.check('the finished picture is a 1080×1350 file', img[0] === 1080 && img[1] === 1350, img);
  const posts = (await t.api('/api/posts?group=queue')).items;
  t.check('the post waits for the owner', posts.length === 1 && posts[0].status === 'due' && posts[0].media[0].width === 1080, posts.map(p => p.status));
  await t.shot('94-ready');
  await t.inTop(s => { s.querySelector('[data-kit="box"]').scrollIntoView(); });
  await t.shot('94b-kit');
  await saveFile(posts[0].media[0].file, 'made-picture.jpg');

  // 4. file and caption leave the panel: copy, share, save
  await page.click('.sheet [data-kit="copy"]');
  await sleep(400);
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  t.check('copy puts the caption on the clipboard', clip === posts[0].caption && clip.length > 10 && (await page.$eval('#toasts', e => e.textContent)).includes('کپشن کپی شد'), clip.slice(0, 60));
  await page.click('.sheet [data-kit="share"]');
  await page.waitForFunction(() => window.__shared, {timeout: 10000});
  const shared = await page.evaluate(() => window.__shared);
  t.check('share hands the JPEG to the phone', shared.length === 1 && /^insta-\d+\.jpg$/.test(shared[0][0]) && shared[0][1] === 'image/jpeg' && shared[0][2] > 20000, shared);
  await sleep(300);
  t.check('and says that the caption is ready to paste', (await page.$eval('#toasts', e => e.textContent)).includes('در اینستاگرام بچسبانش'));
  await page.click('.sheet [data-kit="save"]');
  let saved = [];
  for (let i = 0; i < 40 && !saved.length; i++) { await sleep(250); saved = fs.readdirSync(downloads).filter(f => f.endsWith('.jpg')); }
  const bytes = saved.length ? fs.readFileSync(path.join(downloads, saved[0])) : Buffer.alloc(0);
  t.check('save puts the file in the downloads folder', saved.length === 1 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes.length > 20000, saved);
  await page.click('.sheet [data-kit="done"]');
  await page.waitForFunction(() => [...document.querySelectorAll('.sheet .pill')].some(e => e.textContent.includes('منتشرشده (خودت)')), {timeout: 10000});
  const after = await t.api('/api/status');
  t.check('"I posted it" is recorded', after.counts.due === 0 && after.counts.published_today === 1, after.counts);
  t.check('the kit is gone once posted', (await page.$('.sheet [data-kit="box"]')) === null);
  await t.shot('95-posted');
  await t.closeSheet();

  // 5. a reminder for later, with only a caption
  await t.tab('content');
  await page.click('#fab'); await sleep(400);
  await t.type('textarea[aria-label="کپشن"]', 'یادآوری: عکس ویترین تازه #ویترین');
  await page.click('.sheet button[data-seg="later"]'); await sleep(300);
  t.check('the button says "remind"', (await page.$eval('.sheet [data-go]', e => e.textContent)).includes('یادآوری'));
  await page.click('.sheet [data-go]');
  await page.waitForFunction(() => !document.querySelector('.sheet'), {timeout: 10000});
  await sleep(800);
  const pills = await page.$$eval('#view .card .pill', els => els.map(e => e.textContent));
  t.check('the reminder is listed as one', pills.includes('یادآوری'), pills);
  await t.shot('96-plan');

  // 6. a reel out of one idea: words, a picture per scene, rendered on the device
  await t.tab('home');
  await t.type('textarea[aria-label="ایده"]', 'معرفی کیک هویج خانگی');
  await page.click('[data-make="reel"]');
  await page.waitForSelector('.sheet canvas.stage.tall', {timeout: 120000});
  await sleep(1200);
  const pics = await page.$eval('.sheet [data-pics]', e => e.dataset.pics);
  t.check('every scene got a picture', pics === '4', pics);
  const lines = await page.$$eval('.sheet input[aria-label^="نوشتهٔ صحنهٔ"]', els => els.map(e => e.value));
  t.check('every scene got its words', lines.length === 4 && lines.every(x => x.length > 2), lines);
  await t.shot('97-studio-reel');
  await page.click('.sheet [data-studio-done]');
  await page.waitForSelector('.sheet .kinds', {timeout: 300000});
  const made = await page.evaluate(() => S.made);
  t.check('the reel was encoded frame by frame into MP4', made && made.type === 'video/mp4' && made.way === '1080' && made.size > 300000, made);
  const comp2 = await t.inTop(s => ({tag: (s.querySelector('.mitem .tag') || {}).textContent, kind: s.querySelector('.kinds .on').dataset.kind}));
  t.check('the composer holds a reel', comp2.tag === 'ویدیو' && comp2.kind === 'reel', comp2);
  await page.click('.sheet [data-go]');
  await page.waitForSelector('.sheet video.big', {timeout: 15000});
  await page.waitForFunction(() => { const v = document.querySelector('.sheet video.big'); return v && v.readyState >= 1; }, {timeout: 20000});
  const vid = await page.$eval('.sheet video.big', v => [v.videoWidth, v.videoHeight, Math.round(v.duration * 10) / 10]);
  t.check('it plays as an upright 1080×1920 video of the right length', vid[0] === 1080 && vid[1] === 1920 && Math.abs(vid[2] - 13) < 0.2, vid);
  await t.shot('98-reel-ready');
  console.log('reel file:', await saveFile(made.file, 'made-reel.mp4'), 'bytes');
  await page.click('.sheet [data-kit="share"]');
  await page.waitForFunction(() => window.__shared && window.__shared[0][1] === 'video/mp4', {timeout: 20000});
  t.check('share hands over the MP4', (await page.evaluate(() => window.__shared[0][0])).endsWith('.mp4'));
  await t.closeSheet();

  // 7. the other ways of encoding, each forced once (older phones, browsers without an encoder)
  const quick = async (way, name) => {
    await page.evaluate(w => { S.video = w; }, way);
    await page.click('#fab'); await sleep(400);
    await page.click('.sheet [data-add="ai"]'); await sleep(400);
    await t.type('textarea[aria-label="ایدهٔ پست"]', 'ساعت کاری تازه');
    await t.inTop(s => { s.querySelector('button[data-seg="reel"]').click(); }); await sleep(200);
    await t.inTop(s => { s.querySelector('button[data-seg="3"]').click(); }); await sleep(200);
    await t.inTop(s => { s.querySelector('.sw').click(); }); await sleep(300);        // no AI pictures: drawn backgrounds, fast
    await page.click('.sheet [data-studio-go]');
    await page.waitForSelector('.sheet canvas.stage.tall', {timeout: 60000});
    await sleep(300);
    if (name === 'turned') await t.shot('99-studio-drawn-reel');
    await page.click('.sheet [data-studio-done]');
    await page.waitForFunction(() => !document.querySelector('.sheet canvas.stage') && document.querySelector('.sheet .mitem .tag'), {timeout: 300000});
    const m = await page.evaluate(() => S.made);
    await saveFile(m.file, 'made-reel-' + name + '.' + (m.type === 'video/mp4' ? 'mp4' : 'webm'));
    const probe = await page.evaluate(id => new Promise(res => { const v = document.createElement('video'); v.muted = true; v.onloadedmetadata = () => res([v.videoWidth, v.videoHeight, Math.round(v.duration * 10) / 10]); v.onerror = () => res(['error']); v.src = '/api/file/' + id; }), m.file);
    await t.closeSheet();
    return {m, probe};
  };
  const turned = await quick([1080, true], 'turned');
  t.check('lying on its side, it still plays upright', turned.m.way === '1080 turned' && turned.probe[0] === 1080 && turned.probe[1] === 1920 && Math.abs(turned.probe[2] - 9.8) < 0.2, turned);
  const small = await quick([720, false], 'small');
  t.check('the smaller size works too', small.m.way === '720' && small.probe[0] === 720 && small.probe[1] === 1280, small);
  const live = await quick('live', 'live');
  t.check('recording is the last resort', live.m.way === 'live' && live.m.size > 50000 && live.probe[0] === 720 && live.probe[1] === 1280, live);
  await page.evaluate(() => { S.video = null; });

  // 8. no key, so no AI narrator: the owner's own voice is recorded and laid on the reel
  const drawnReel = async (ideaText, scenes) => {
    await page.click('#fab'); await sleep(400);
    await page.click('.sheet [data-add="ai"]'); await sleep(400);
    await t.type('textarea[aria-label="ایدهٔ پست"]', ideaText);
    await t.inTop(s => { s.querySelector('button[data-seg="reel"]').click(); }); await sleep(200);
    await t.inTop((s, n) => { s.querySelector('button[data-seg="' + n + '"]').click(); }, scenes); await sleep(200);
    await t.inTop(s => { s.querySelector('[data-opt="pics"] .sw').click(); }); await sleep(300);
  };
  const filmed = async name => {
    await page.click('.sheet [data-studio-done]');
    await page.waitForFunction(() => !document.querySelector('.sheet canvas.stage') && document.querySelector('.sheet .mitem .tag'), {timeout: 300000});
    const m = await page.evaluate(() => S.made);
    const file = name + '.' + (m.type === 'video/mp4' ? 'mp4' : 'webm');
    await saveFile(m.file, file);
    return {m, file};
  };
  await page.evaluate(() => { S.video = [720, false]; });
  await drawnReel('ساعت کاری تازه', 3);
  const noKey = await t.inTop(s => { const r = s.querySelector('[data-opt="voice"]'); return {text: r.textContent, sw: !!r.querySelector('.sw')}; });
  t.check('the form says the narrator has to be downloaded first', noKey.text.includes('گویندهٔ فارسی هنوز روی این دستگاه نیست') && noKey.text.includes('صدای خودت') && !noKey.sw, noKey);
  t.check('and offers the download right there', await t.inTop(s => !!s.querySelector('[data-pack-do="get"]')));
  await t.shot('100-form-no-key');
  await page.click('.sheet [data-studio-go]');
  await page.waitForSelector('.sheet canvas.stage.tall', {timeout: 60000});
  await sleep(300);
  const silent = await voiceCard();
  t.check('without the narrator the reel is silent and offers the microphone', silent.mode === 'none' && !silent.ai && !silent.play && silent.text.includes('ضبط صدای خودم') && silent.get && silent.pack === 'none', silent);
  await page.click('.sheet [data-voice-do="record"]');
  await page.waitForSelector('.sheet [data-rec="start"]', {timeout: 8000});
  const script = await t.inTop(s => [...s.querySelectorAll('.line')].map(e => e.textContent));
  t.check('the recorder shows what to read, scene by scene', script.length === 3 && script.every(x => x.length > 5), script);
  await t.shot('101-record');
  await page.click('.sheet [data-rec="start"]');
  await page.waitForSelector('.sheet [data-rec="stop"]', {timeout: 15000});
  await sleep(4300);
  await page.click('.sheet [data-rec="stop"]');
  await page.waitForSelector('.sheet [data-rec="use"]', {timeout: 20000});
  await t.shot('102-recorded');
  await page.click('.sheet [data-rec="use"]');
  await page.waitForFunction(() => { const c = document.querySelector('.sheet [data-voice]'); return c && c.dataset.voice === 'mine'; }, {timeout: 8000});
  const mine = await voiceCard();
  t.check('the recording becomes the sound of the reel', mine.play && mine.text.includes('صدای خودت'), mine);
  await t.shot('103-own-voice');
  const own = await filmed('made-reel-mine');
  t.check('the reel carries the recorded voice and lasts as long as it', own.m.voice === 'mine' && ['aac', 'opus'].includes(own.m.sound) && own.m.seconds > 4.8 && own.m.seconds < 7.5 && own.m.type === 'video/mp4', own.m);
  sounds[own.file] = Object.assign({w: 720, h: 1280}, own.m);
  await t.closeSheet();

  // 8b. the free narrator: downloaded once (here: small stand-ins from the simulator), it reads every scene on the device
  await drawnReel('ساعت کاری تازه: هر روز ۸ تا ۲۳', 3);
  await page.click('.sheet [data-studio-go]');
  await page.waitForSelector('.sheet canvas.stage.tall', {timeout: 60000});
  await sleep(300);
  await page.click('.sheet [data-voice] [data-pack-do="get"]');
  await page.waitForFunction(() => { const c = document.querySelector('.sheet [data-voice]'); return c && c.dataset.voice === 'ai'; }, {timeout: 60000});
  await sleep(400);
  const dev = await voiceCard();
  t.check('once it is downloaded the narrator reads every scene at once', dev.speaker === 'device' && dev.says.length === 3 && dev.secs.length === 3 && dev.secs.every(x => x > 0.5 && x < 30) && dev.play && !dev.get, dev);
  const pk = await t.api('/api/studio/pack');
  t.check('the narrator is on the device now', pk.state === 'ready' && pk.pct === 100, pk);
  const read1 = voiceCalls.slice(-1)[0];
  t.check('the lines were read on the device, by the chosen narrator', read1 && read1.speaker === 'device' && read1.texts.length === 3, read1);
  await t.shot('103b-device-narrator');
  await page.click('.sheet [data-voice-do="play"]');
  await sleep(1200);
  const devLine = 'هر روز از ساعت ۸ صبح تا ۱۱ شب باز هستیم.';
  await t.type('textarea[aria-label="متن گوینده 3"]', devLine);
  const devBefore = voiceCalls.length;
  const devMade = await filmed('made-reel-device');
  const dev2 = voiceCalls.slice(devBefore);
  t.check('a changed line is read again by the device, alone', dev2.length === 1 && JSON.stringify(dev2[0].texts) === JSON.stringify([devLine]) && dev2[0].speaker === 'device', dev2);
  const spoken = 'هر روز از ساعت هشت صبح تا یازده شب باز هستیم.', devSecs = [dev.secs[0], dev.secs[1], 0.3 + 0.03 * (2 * spoken.length + 3)];
  const devWant = devSecs.reduce((sum, x) => sum + Math.max(3.2, x + 0.95), 0) + 0.2;
  t.check('the reel carries that narration and lasts as long as it needs', devMade.m.voice === 'ai' && ['aac', 'opus'].includes(devMade.m.sound) && devMade.m.type === 'video/mp4' && Math.abs(devMade.m.seconds - devWant) < 0.3, [devMade.m, devWant, devSecs]);
  sounds[devMade.file] = Object.assign({w: 720, h: 1280, speech: 3}, devMade.m);
  await t.closeSheet();
  await page.evaluate(() => { S.video = null; });
  await t.tab('home');
  await sleep(500);
  const homeNow = await page.evaluate(() => ({hint: !!document.querySelector('[data-home-voice]'), text: document.querySelector('#view .card').textContent}));
  t.check('the home screen now makes videos with a narrator', !homeNow.hint && homeNow.text.includes('با صدای گوینده'), homeNow);

  // 9. a Pollinations key switches the AI narrator on; the key is tried out from the settings
  await t.tab('agent');
  await page.click('#open-settings');
  await page.waitForSelector('.sheet details[data-sec="studio"]', {timeout: 8000});
  await page.evaluate(() => document.querySelector('.sheet details[data-sec="studio"] summary').click());
  await sleep(300);
  await t.type('input[aria-label="کلید Pollinations"]', 'sk_wrong_key');
  await page.click('.sheet [data-key-test]');
  await page.waitForFunction(() => document.querySelector('#toasts').textContent.includes('این کلید را نپذیرفت'), {timeout: 15000});
  t.check('a wrong key is called wrong', true);
  await t.type('input[aria-label="کلید Pollinations"]', AI_KEY);
  await page.click('.sheet [data-key-test]');
  await page.waitForFunction(() => document.querySelector('#toasts').textContent.includes('کلید پذیرفته شد ✓'), {timeout: 15000});
  const told = await page.$eval('#toasts', e => e.textContent);
  t.check('a good key is accepted and its credit is shown', told.includes('۱٫۲۵'), told);
  await t.shot('104-key-tested');
  await t.inTop(s => { s.querySelector('select[aria-label="گوینده"]').value = 'onyx'; s.querySelector('details[data-sec="studio"] .btn.pri').click(); });
  await sleep(800);
  const st1 = await t.api('/api/status');
  t.check('the narrator is ready, with the chosen speaker', st1.studio.voice === true && st1.studio.speaker === 'onyx' && st1.studio.pollen === true, st1.studio);
  await t.closeSheet();

  // 10. a narrated reel: the narrator reads every scene, each scene lasts as long as its voice
  await t.tab('home');
  await t.type('textarea[aria-label="ایده"]', 'معرفی کیک هویج خانگی');
  await page.click('[data-make="reel"]');
  await page.waitForSelector('.sheet canvas.stage.tall', {timeout: 180000});
  await sleep(1000);
  const told1 = await voiceCard();
  t.check('every scene has its narration', told1.mode === 'ai' && told1.says.length === 4 && told1.says.every(x => x.length > 12) && told1.speaker === 'onyx' && told1.play, told1);
  t.check('all pictures are there as well', (await page.$eval('.sheet [data-pics]', e => e.dataset.pics)) === '4');
  await t.shot('105-narrated');
  await t.inTop(s => { s.querySelector('[data-voice]').scrollIntoView(); });
  await t.shot('105b-narration-lines');
  await page.click('.sheet [data-voice-do="play"]');
  await sleep(1500);
  t.check('the preview plays with its sound', (await page.$eval('#toasts', e => e.textContent)).indexOf('خطا') < 0);
  const line = 'کیک هویج ما هر روز صبح تازه پخته می‌شود و بوی دارچینش تا سر کوچه می‌رود.';
  await t.type('textarea[aria-label="متن گوینده 2"]', line);
  const stale = await t.inTop(s => [...s.querySelectorAll('[data-voice] .amber')].filter(e => !e.classList.contains('hide')).length);
  t.check('a changed line is marked for reading again', stale === 1, stale);
  const before = voiceCalls.length;
  const told2 = await filmed('made-reel-voice');
  const says = told1.says.slice(); says[1] = line;
  t.check('only the changed line was read again', voiceCalls.length === before + 1 && JSON.stringify(voiceCalls[before].texts) === JSON.stringify([line]) && voiceCalls[before].speaker === 'onyx', voiceCalls.slice(before));
  t.check('the narrated reel is a full-size MP4 with a sound track', told2.m.type === 'video/mp4' && told2.m.way === '1080' && told2.m.voice === 'ai' && ['aac', 'opus'].includes(told2.m.sound), told2.m);
  t.check('it lasts as long as the narration needs', Math.abs(told2.m.seconds - reelSeconds(says)) < 0.12, [told2.m.seconds, reelSeconds(says)]);
  sounds[told2.file] = Object.assign({w: 1080, h: 1920, speech: 4}, told2.m);
  await page.click('.sheet [data-go]');
  await page.waitForSelector('.sheet video.big', {timeout: 15000});
  await page.waitForFunction(() => { const v = document.querySelector('.sheet video.big'); return v && v.readyState >= 1; }, {timeout: 20000});
  const heard = await page.$eval('.sheet video.big', v => [v.videoWidth, v.videoHeight, Math.round(v.duration * 10) / 10, v.mozHasAudio, v.webkitAudioDecodedByteCount, (v.audioTracks || []).length]);
  t.check('the browser plays it at the right length', heard[0] === 1080 && heard[1] === 1920 && Math.abs(heard[2] - told2.m.seconds) < 0.2, heard);
  await t.shot('106-narrated-ready');
  await t.closeSheet();

  // 11. the last resort (recording the canvas) carries the narration too
  await page.evaluate(() => { S.video = 'live'; });
  await drawnReel('ساعت کاری تازه', 3);
  const withKey = await t.inTop(s => { const r = s.querySelector('[data-opt="voice"]'); return {text: r.textContent, on: r.querySelector('.sw').getAttribute('aria-checked')}; });
  t.check('with a key the narrator is on by default', withKey.on === 'true' && withKey.text.includes('می‌خواند'), withKey);
  await page.click('.sheet [data-studio-go]');
  await page.waitForSelector('.sheet canvas.stage.tall', {timeout: 60000});
  await sleep(300);
  const rec = await filmed('made-reel-live-voice');
  t.check('the recorded reel has its sound', rec.m.way === 'live' && rec.m.sound === 'recorded' && rec.m.voice === 'ai', rec.m);
  sounds[rec.file] = Object.assign({w: 720, h: 1280, loose: true}, rec.m);
  await t.closeSheet();
  await page.evaluate(() => { S.video = null; });

  // 11b. Phones encode the sound as AAC; this browser has no AAC encoder. So AAC made by ffmpeg (serve.py prepares it)
  //      is put through the panel's own MP4 writer, and check_made.py lets a player decode the result.
  const tone = path.join(ASSETS, 'tone.aac');
  if (fs.existsSync(tone)) {
    const adts = fs.readFileSync(tone), frames = [];
    for (let at = 0; at + 7 <= adts.length;) {
      if (adts[at] !== 0xff || (adts[at + 1] & 0xf6) !== 0xf0) throw new Error('tone.aac: no ADTS frame at byte ' + at);
      const len = ((adts[at + 3] & 3) << 11) | (adts[at + 4] << 3) | (adts[at + 5] >> 5), head = (adts[at + 1] & 1) ? 7 : 9;
      frames.push(adts.subarray(at + head, at + len).toString('base64'));
      at += len;
    }
    const kind = (adts[2] >> 6) + 1, freq = (adts[2] >> 2) & 15, chans = ((adts[2] & 1) << 2) | (adts[3] >> 6);
    const rate = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000][freq];
    const aac = await page.evaluate(async (frames, asc, chans, rate) => {
      const bytes = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
      const seconds = frames.length * 1024 / rate, stage = blank(720, 1280);
      const m = Object.assign(reelTimes([seconds - 0.2]), {scenes: [{img: null, text: 'AAC'}], sub: '', handle: '', look: 2});
      const video = await encodeFrames(stage, t => paintReel(stage, m, t), seconds, REEL_FPS, false, () => {}, {on: false});
      const blob = mp4File(video, {kind: 'aac', channels: chans, rate, desc: Uint8Array.from(asc), samples: frames.map(f => ({data: bytes(f), dur: 1024}))});
      const u = new Uint8Array(await blob.arrayBuffer());
      let str = '';
      for (let i = 0; i < u.length; i += 32768) str += String.fromCharCode.apply(null, u.subarray(i, i + 32768));
      return {b64: btoa(str), seconds, type: blob.type, pictures: video.samples.length};
    }, frames, [(kind << 3) | (freq >> 1), ((freq & 1) << 7) | (chans << 3)], chans, rate);
    fs.writeFileSync(path.join(out, 'made-reel-aac.mp4'), Buffer.from(aac.b64, 'base64'));
    t.check('AAC sound goes through the panel\'s own MP4 writer', kind === 2 && rate === 48000 && chans === 1 && frames.length > 100 && aac.type === 'video/mp4' && aac.pictures === Math.round(aac.seconds * 30), [kind, rate, chans, frames.length, aac.seconds, aac.pictures]);
    sounds['made-reel-aac.mp4'] = {w: 720, h: 1280, speech: 3, seconds: aac.seconds, sound: 'aac', voice: 'ffmpeg\'s AAC through the panel\'s writer'};
  } else console.log('SKIP  the AAC writer check: no ffmpeg here, so there is no tone.aac (pip install imageio-ffmpeg)');
  fs.writeFileSync(path.join(out, 'made.json'), JSON.stringify(sounds, null, 1));

  // 12. settings of the studio; nothing hostile ran
  await t.tab('agent');
  await page.click('#open-settings');
  await page.waitForSelector('.sheet details[data-sec="studio"]', {timeout: 8000});
  await page.evaluate(() => document.querySelector('.sheet details[data-sec="studio"] summary').click());
  await sleep(300);
  await t.shot('99b-settings-studio');
  const inSet = await t.inTop(s => { const c = s.querySelector('[data-sec="pack"]'); return {text: c.textContent, remove: !!c.querySelector('[data-pack-do="remove"]'),
    names: [...s.querySelector('select[aria-label="گوینده"]').options].map(o => o.value)}; });
  t.check('the settings show the narrator on the device and list every speaker', inSet.remove && inSet.text.includes('نصب است') && inSet.names[0] === '' && inSet.names[1] === 'device' && inSet.names.includes('onyx'), inSet);
  await page.click('.sheet [data-sec="pack"] [data-pack-do="remove"]');
  await page.waitForSelector('.sheet [data-sec="pack"] [data-pack-do="get"]', {timeout: 15000});
  t.check('it can be removed again', (await t.api('/api/studio/pack')).state === 'none');
  await page.evaluate(() => { const d = document.querySelector('.sheet details[data-sec="studio"]'); d.querySelector('select').value = 'off'; d.querySelector('input[aria-label="کلید Pollinations"]').value = 'sk_test_123'; d.querySelector('.btn.pri').click(); });
  await sleep(800);
  const set = await t.api('/api/settings');
  t.check('the picture service and the key are saved; the key is not sent back', set.studio.image === 'off' && set.studio.pollen === '' && set.studio.pollen_set === true, set.studio);
  await t.closeSheet();
  t.check('no script from the idea ran', (await page.evaluate(() => window.__xss)) === undefined);
} catch (e) {
  t.fail();
  console.log('EXCEPTION', e.message);
  if (process.env.GITHUB_ACTIONS) console.log('::error title=Panel script stopped::' + String(e.message).replace(/\r?\n/g, ' '));
  await page.screenshot({path: out + '/99-exception.png'});
}
// a video thumbnail that is redrawn while it still loads shows up as an aborted request: that is not a fault
await t.finish('BY HAND', /status of 4\d\d|\/api\/file\/\w+(#t=0\.1)? net::ERR_ABORTED/);
