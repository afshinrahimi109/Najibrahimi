/* زنگ تماس و بیپ‌ها — با Web Audio ساخته می‌شوند، بدون فایل صوتی */

export function createRinger() {
  let ctx = null;
  let timer = null;
  let vibrateTimer = null;
  let enabled = true;

  function ac() {
    if (!ctx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return null;
      ctx = new Ctx();
    }
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    return ctx;
  }

  /** یک تن ساده با پوش صدا */
  function tone(freqs, start, dur, peak = 0.16) {
    const c = ac();
    if (!c) return;
    const t0 = c.currentTime + start;
    const g = c.createGain();
    g.connect(c.destination);
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(peak, t0 + 0.04);
    g.gain.setValueAtTime(peak, t0 + dur - 0.08);
    g.gain.linearRampToValueAtTime(0, t0 + dur);
    for (const f of freqs) {
      const o = c.createOscillator();
      o.type = 'sine';
      o.frequency.value = f;
      o.connect(g);
      o.start(t0);
      o.stop(t0 + dur + 0.02);
    }
  }

  function stopAll() {
    clearInterval(timer);
    clearInterval(vibrateTimer);
    timer = null;
    vibrateTimer = null;
    try { navigator.vibrate?.(0); } catch { /* noop */ }
  }

  function loop(fn, periodMs) {
    stopAll();
    fn();
    timer = setInterval(fn, periodMs);
  }

  return {
    setEnabled(v) { enabled = v; if (!v) stopAll(); },

    /** آماده‌سازی AudioContext با اولین لمس کاربر (لازم برای iOS) */
    prime() {
      const c = ac();
      if (!c) return;
      try {
        const g = c.createGain();
        g.gain.value = 0.0001;
        g.connect(c.destination);
        const o = c.createOscillator();
        o.connect(g);
        o.start();
        o.stop(c.currentTime + 0.01);
      } catch { /* noop */ }
    },

    /** زنگ تماس ورودی */
    incoming() {
      if (!enabled) return;
      const play = () => {
        tone([440, 480], 0, 0.42);
        tone([440, 480], 0.52, 0.42);
      };
      loop(play, 2600);
      try {
        const buzz = () => navigator.vibrate?.([420, 180, 420, 900]);
        buzz();
        vibrateTimer = setInterval(buzz, 2600);
      } catch { /* noop */ }
    },

    /** بوق انتظار برای تماس خروجی */
    outgoing() {
      if (!enabled) return;
      loop(() => tone([425], 0, 0.9, 0.1), 4000);
    },

    /** اتصال برقرار شد */
    connected() {
      stopAll();
      if (!enabled) return;
      tone([660], 0, 0.1, 0.18);
      tone([880], 0.11, 0.14, 0.16);
    },

    /** پایان تماس */
    ended() {
      stopAll();
      if (!enabled) return;
      tone([400], 0, 0.13, 0.14);
      tone([300], 0.15, 0.2, 0.12);
    },

    /** خطا */
    error() {
      stopAll();
      if (!enabled) return;
      tone([220], 0, 0.2, 0.16);
    },

    stop() { stopAll(); },
  };
}
