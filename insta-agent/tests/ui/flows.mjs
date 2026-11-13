import {start, BASE, ASSETS, out, sleep} from './lib.mjs';
const t = await start();
const {page} = t;
try {
  await page.goto(BASE + '/', {waitUntil: 'networkidle0'});
  await page.waitForSelector('#nav button[data-tab="home"]', {timeout: 15000});
  t.check('home shows the page handle', (await page.$eval('#top h1', e => e.textContent)) === '@demo.cafe');
  t.check('fab hidden on home', await page.$eval('#fab', e => e.classList.contains('hide')));

  // composer: a wide PNG from the "gallery" becomes a JPEG and is published now
  await t.tab('content');
  await page.click('#fab'); await sleep(400);
  await (await page.$('.sheet input[type=file]')).uploadFile(ASSETS + '/wide.png');
  await page.waitForSelector('.sheet .mitem img', {timeout: 15000});
  await t.type('textarea[aria-label="کپشن"]', 'تست انتشار از پنل ☕️\n#کافه #تست');
  await t.shot('10-composer');
  t.check('counter counts hashtags', (await page.$eval('.sheet .muted.sm.row', e => e.textContent)).includes('۲ هشتگ'));
  await page.click('.sheet [data-go]');
  t.check('image published from the panel', await t.waitText('منتشر شد ✓ —', 20000));
  await t.shot('11-published');
  let media = await t.api('/api/media?refresh=1');
  t.check('new post is first on the page grid', media.items[0].caption.startsWith('تست انتشار از پنل'), media.items[0].caption);
  const done = await t.api('/api/posts?group=published');
  t.check('uploaded file became a JPEG of the same shape', done.items[0].media[0].width === 1200 && done.items[0].media[0].height === 900, done.items[0].media[0]);
  await t.closeSheet();

  // a very tall image is cropped to 4:5
  await page.click('#fab'); await sleep(400);
  await (await page.$('.sheet input[type=file]')).uploadFile(ASSETS + '/tall.png');
  await page.waitForSelector('.sheet .mitem img', {timeout: 15000});
  t.check('crop notice shown', await t.waitText('برش خورد', 4000));
  await t.clickText('پیش‌نویس');
  await sleep(900);
  let drafts = await t.api('/api/posts?group=drafts');
  const m0 = drafts.items[0].media[0];
  t.check('tall image cropped to 4:5', Math.abs(m0.width / m0.height - 0.8) < 0.01, m0);
  t.check('landed on the drafts list', await page.evaluate(() => !!document.querySelector('button[data-post]')));

  // schedule that draft with a suggested slot
  await page.click('button[data-post]'); await sleep(500);
  await t.clickText('ویرایش'); await sleep(500);
  await t.type('textarea[aria-label="کپشن"]', 'پست زمان‌بندی‌شده');
  await t.inTop(s => s.querySelector('button[data-seg="later"]').click()); await sleep(900);
  await t.inTop(s => s.querySelector('.chips .chip').click()); await sleep(300);
  await t.shot('12-schedule');
  await page.click('.sheet [data-go]'); await sleep(1000);
  const queue = await t.api('/api/posts?group=queue');
  t.check('post scheduled in the future', queue.items.length === 1 && queue.items[0].status === 'scheduled' && queue.items[0].scheduled_at > Date.now() / 1000 + 600, queue.items.map(p => [p.status, p.scheduled_at]));
  t.check('queue lists it', await t.waitText('پست زمان‌بندی‌شده', 3000));
  await t.shot('13-queue');

  // reel
  await page.click('#fab'); await sleep(400);
  await page.click('.sheet .kinds button[data-kind="reel"]');
  await (await page.$('.sheet input[type=file]')).uploadFile(ASSETS + '/clip.mp4');
  await page.waitForFunction(() => { const s = [...document.querySelectorAll('.sheet')].pop(); const g = s && s.querySelector('.mitem .tag'); return g && g.textContent === 'ویدیو'; }, {timeout: 15000});
  await t.type('textarea[aria-label="کپشن"]', 'ریل آزمایشی 🎬');
  await page.click('.sheet [data-go]');
  t.check('publishing progress is shown', await t.waitText('در حال انتشار', 6000));
  t.check('reel published', await t.waitText('منتشر شد ✓ —', 25000));
  await t.closeSheet();

  // caption helper
  await page.click('#fab'); await sleep(400);
  await t.clickText('کپشن پیشنهادی');
  await t.type('input[aria-label="موضوع"]', 'لاتهٔ پاییزی');
  await t.clickText('بنویس');
  await page.waitForFunction(() => { const s = [...document.querySelectorAll('.sheet')].pop(); return s && s.querySelectorAll('[data-pick]').length >= 3; }, {timeout: 60000});
  await t.shot('14-captions');
  await t.inTop(s => s.querySelector('[data-pick]').click()); await sleep(300);
  t.check('picked caption lands in the composer', (await page.$eval('.sheet textarea[aria-label="کپشن"]', e => e.value)).includes('لاتهٔ پاییزی'));
  await t.clickText('هشتگ پیشنهادی');
  await t.type('input[aria-label="موضوع"]', 'قهوه دمی');
  await t.clickText('بنویس');
  await page.waitForFunction(() => { const s = [...document.querySelectorAll('.sheet')].pop(); return s && s.querySelectorAll('.chip').length >= 3; }, {timeout: 60000});
  await t.clickText('افزودن همه به کپشن');
  t.check('hashtags added to the caption', (await page.$eval('.sheet textarea[aria-label="کپشن"]', e => e.value)).includes('#قهوه'));
  await t.closeSheet();

  // page grid and media detail
  await page.click('button[data-seg="page"]');
  await page.waitForSelector('.tile', {timeout: 10000});
  await t.shot('15-page-grid');
  await page.click('.tile');
  t.check('media detail shows insights', await t.waitText('ریچ', 8000));
  await t.shot('16-media-detail');
  await t.closeSheet();

  // inbox: hostile text is inert; reply works
  await t.tab('inbox');
  await page.waitForSelector('.thread', {timeout: 10000});
  t.check('hostile comment shown as text', await page.evaluate(() => document.body.innerText.includes('<img src=x onerror="window.__xss=1">')));
  const before = (await t.api('/api/status')).counts.open_comments;
  await page.evaluate(() => {
    const card = [...document.querySelectorAll('.thread')].find(c => c.innerText.includes('قیمت لاته چنده؟'));
    card.querySelector('textarea').value = 'سلام 🌹 ۹۵ هزار تومان'; card.querySelector('.replybar .btn.pri').click();
  });
  t.check('reply toast', await t.waitText('پاسخ فرستاده شد', 8000));
  await sleep(800);
  t.check('thread left the waiting list', (await t.api('/api/status')).counts.open_comments === before - 1);
  await page.evaluate(() => { const card = [...document.querySelectorAll('.thread')].find(c => c.innerText.includes('follow-shop')); card.querySelector('.iconbtn[aria-label="بیشتر"]').click(); });
  await sleep(300);
  await t.shot('21-comment-menu');
  await t.clickText('مخفی‌کردن کامنت');
  t.check('hide toast', await t.waitText('کامنت مخفی شد', 8000));
  await sleep(500);
  await page.evaluate(() => { document.querySelector('.thread .iconbtn[aria-label="بیشتر"]').click(); });
  await sleep(300);
  await t.clickText('پیشنهاد پاسخ از دستیار');
  t.check('suggestion appears in the reply box', await t.waitText('پیشنهاد دستیار در کادر پایین', 60000));
  t.check('reply box holds the suggestion', await page.evaluate(() => [...document.querySelectorAll('.thread textarea')].some(x => x.value.length > 5)));
  await t.shot('22-suggestion');
  // a half-written reply is still there after the list redraws itself (something else changed on the page meanwhile)
  const pick = text => [...document.querySelectorAll('.thread')].find(c => c.innerText.includes(text));
  await page.evaluate(`(${pick})('آدرس دقیق').querySelector('textarea').focus()`);
  await page.keyboard.type('نیمه‌کاره');
  await page.evaluate(() => document.activeElement.blur());
  const other = (await t.api('/api/comments?filter=open')).items.find(x => x.top.text.includes('دفعهٔ قبل'));
  await page.evaluate(id => fetch('/api/comments/' + id + '/dismiss', {method: 'POST', headers: {'X-IA': '1', 'Content-Type': 'application/json'}, body: '{}'}), other.id);
  await page.waitForFunction(`!(${pick})('دفعهٔ قبل عالی بود')`, {timeout: 12000});
  t.check('half-written reply survives a redraw', await page.evaluate(`(${pick})('آدرس دقیق').querySelector('textarea').value`) === 'نیمه‌کاره');
  // hidden filter shows the hidden comment and can bring it back
  await t.clickText('مخفی‌شده'); await sleep(900);
  t.check('hidden filter lists the spam comment', await page.evaluate(() => document.body.innerText.includes('follow-shop')));
  await t.clickText('پاسخ‌نداده'); await sleep(700);

  // DMs
  await page.click('button[data-seg="dm"]');
  await page.waitForSelector('button[data-conv]', {timeout: 10000});
  t.check('hostile DM shown as text in the list', await page.evaluate(() => document.body.innerText.includes('<img src=x')));
  await t.shot('23-dm-list');
  await page.evaluate(() => { [...document.querySelectorAll('button[data-conv]')].find(b => b.innerText.includes('elham.gh')).click(); });
  await page.waitForSelector('.sheet .bubble', {timeout: 8000});
  await t.type('textarea[aria-label="پیام"]', 'سلام 🌹 هر روز ۹ تا ۲۳');
  await t.inTop(s => s.querySelector('.foot .btn.pri').click());
  await page.waitForFunction(() => [...document.querySelectorAll('.sheet .bubble.me')].some(b => b.innerText.includes('هر روز ۹ تا ۲۳')), {timeout: 8000});
  t.check('dm sent and shown', true);
  await t.shot('24-dm-chat');
  await t.closeSheet();
  await page.evaluate(() => { [...document.querySelectorAll('button[data-conv]')].find(b => b.innerText.includes('bahar.s')).click(); });
  t.check('old chat explains the 24h rule', await t.waitText('بیش از ۲۴ ساعت گذشته', 6000));
  await t.closeSheet();

  // stats
  await t.tab('stats');
  await page.waitForSelector('.kpi', {timeout: 10000});
  await t.shot('30-stats');
  await t.clickText('نمایش سن، جنسیت و شهر');
  t.check('audience loaded', await t.waitText('جنسیت', 8000));
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await t.shot('31-stats-bottom');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.click('button[data-seg="28"]'); await sleep(1200);
  t.check('28-day view loads', await page.evaluate(() => document.querySelectorAll('.kpi').length >= 8));

  // agent tab: rule, brakes, settings, assistant, help
  await t.tab('agent');
  await page.waitForSelector('button[data-newrule="comment"]', {timeout: 10000});
  await t.shot('40-agent');
  await page.click('button[data-newrule="comment"]'); await sleep(400);
  await t.type('input[aria-label="نام قانون"]', 'آدرس');
  await t.type('textarea[aria-label="کلمه‌ها"]', 'آدرس، کجایید، لوکیشن');
  await t.type('textarea[aria-label="پاسخ‌ها"]', 'سلام {username} 🌹 آدرس در بیوی پیج هست.');
  await t.shot('41-rule-editor');
  await t.clickText('ذخیره');
  t.check('rule saved toast', await t.waitText('قانون ذخیره شد', 8000));
  const rules = await t.api('/api/rules');
  const made = rules.items.find(r => r.name === 'آدرس');
  t.check('rule stored with keywords and reply', !!made && made.keywords.length === 3 && made.replies[0].includes('{username}'), made);
  await page.click('#open-settings');
  await page.waitForSelector('.sheet details[data-sec="media"]', {timeout: 8000});
  await page.evaluate(() => { document.querySelector('.sheet details[data-sec="media"] summary').click(); });
  await t.shot('42-settings-media');
  await page.evaluate(() => { document.querySelector('.sheet details[data-sec="media"] summary').click(); document.querySelector('.sheet details[data-sec="brand"] summary').click(); });
  await page.evaluate(() => { const d = document.querySelector('.sheet details[data-sec="brand"]'); d.querySelector('textarea').value = 'کافهٔ آزمایشی'; d.querySelector('.btn.pri').click(); });
  t.check('settings saved', await t.waitText('ذخیره شد', 8000));
  t.check('brand persisted', (await t.api('/api/settings')).brand.about === 'کافهٔ آزمایشی');
  await t.closeSheet();
  await t.clickText('دستیار'); await sleep(500);
  await t.clickText('وضعیت پیج چطور است؟');
  await page.waitForFunction(() => document.querySelectorAll('.sheet .bubble:not(.me):not(.muted)').length >= 1, {timeout: 90000});
  await t.shot('43-assistant');
  t.check('assistant answered with page facts', await page.evaluate(() => [...document.querySelectorAll('.sheet .bubble:not(.me)')].pop().innerText.includes('دنبال')));
  await t.closeSheet();
  await t.clickText('راهنما');
  await t.shot('44-help');
  await t.closeSheet();

  // notifications
  await page.click('#top .iconbtn');
  await page.waitForSelector('.sheet .logline', {timeout: 8000});
  await t.shot('50-notes');
  await t.closeSheet(); await sleep(600);
  t.check('unread badge cleared', (await page.$('#top .badge')) === null);

  // planner
  await t.tab('content');
  await page.click('button[data-seg="drafts"]'); await sleep(700);
  await t.clickText('چیدن برنامهٔ محتوایی'); await sleep(400);
  await t.clickText('بچین');
  t.check('planner created drafts', await t.waitText('پیش‌نویس با کپشن ساخته شد', 90000));
  await sleep(900);
  t.check('drafts are listed', await page.evaluate(() => document.querySelectorAll('button[data-post]').length >= 5));
  await t.shot('51-drafts');

  // master switch
  await t.tab('home');
  await page.click('.sw'); await sleep(1200);
  t.check('pause shown in the header', (await page.$eval('#top .sub', e => e.textContent)).includes('متوقف'));
  await page.click('.sw'); await sleep(900);
  t.check('resume shown in the header', (await page.$eval('#top .sub', e => e.textContent)).includes('روشن'));

  t.check('no script from hostile content ran', (await page.evaluate(() => window.__xss)) === undefined);
  t.check('no sheet left open', (await t.sheets()) === 0);
  await page.emulateMediaFeatures([{name: 'prefers-color-scheme', value: 'dark'}]);
  await t.tab('home'); await t.shot('60-dark-home');
  await t.tab('inbox'); await t.shot('61-dark-inbox');
} catch (e) {
  t.fail();
  console.log('EXCEPTION', e.message);
  if (process.env.GITHUB_ACTIONS) console.log('::error title=Panel script stopped::' + String(e.message).replace(/\r?\n/g, ' '));
  await page.screenshot({path: out + '/99-exception.png'});
}
await t.finish('UI FLOWS');
