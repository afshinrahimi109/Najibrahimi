class SoundFXManager {
  private ctx: AudioContext | null = null;
  public sfxEnabled = true;
  public musicEnabled = true;
  public get muted(): boolean {
    return !this.sfxEnabled && !this.musicEnabled;
  }
  public set muted(value: boolean) {
    this.sfxEnabled = !value;
    this.setMusicEnabled(!value);
  }
  private musicTimer: number | null = null;
  private musicStep = 0;

  // Authentic Korean Pentatonic Scale (Pyongjo: C, D, F, G, A)
  private readonly gayageumScale = [
    261.63, // C4
    293.66, // D4
    349.23, // F4
    392.0, // G4
    440.0, // A4
    523.25, // C5
    587.33, // D5
    698.46, // F5
    783.99, // G5
  ];

  // Peaceful melodic motif inspired by Arirang & Joseon courtyard music
  private readonly melodyPattern = [
    0, 1, 2, 3, 4, 3, 2, 1,
    3, 4, 5, 6, 5, 4, 3, -1,
    5, 4, 3, 2, 3, 1, 0, -1,
    1, 3, 4, 3, 2, 1, 0, -1,
  ];

  private ensureContext(): AudioContext | null {
    if (!this.ctx && typeof window !== 'undefined') {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (AudioCtx) {
        this.ctx = new AudioCtx();
      }
    }
    if (this.ctx && this.ctx.state === 'suspended') {
      this.ctx.resume().catch(() => {});
    }
    return this.ctx;
  }

  public unlockAndStartMusic(): void {
    this.ensureContext();
    if (this.musicEnabled && this.musicTimer === null) {
      this.startMusicLoop();
    }
  }

  public setMusicEnabled(enabled: boolean): void {
    this.musicEnabled = enabled;
    if (enabled) {
      this.ensureContext();
      this.startMusicLoop();
    } else {
      this.stopMusicLoop();
    }
  }

  public setSfxEnabled(enabled: boolean): void {
    this.sfxEnabled = enabled;
  }

  private startMusicLoop(): void {
    if (this.musicTimer !== null || typeof window === 'undefined') return;
    this.musicTimer = window.setInterval(() => {
      if (!this.musicEnabled) return;
      const ctx = this.ctx;
      if (!ctx || ctx.state !== 'running') return;

      const idx = this.melodyPattern[this.musicStep % this.melodyPattern.length];
      const stepInBar = this.musicStep % 8;
      this.musicStep++;

      const now = ctx.currentTime;

      // Warm bass drone on beat 0 of every bar
      if (stepInBar === 0) {
        const bassOsc = ctx.createOscillator();
        const bassGain = ctx.createGain();
        bassOsc.type = 'sine';
        bassOsc.frequency.setValueAtTime(130.81, now); // C3
        bassGain.gain.setValueAtTime(0.001, now);
        bassGain.gain.linearRampToValueAtTime(0.028, now + 0.15);
        bassGain.gain.exponentialRampToValueAtTime(0.0008, now + 2.8);
        bassOsc.connect(bassGain).connect(ctx.destination);
        bassOsc.start(now);
        bassOsc.stop(now + 2.9);
      }

      if (idx >= 0) {
        const freq = this.gayageumScale[idx];
        this.pluckGayageumNote(ctx, freq, now, 0.036);
      }
    }, 520);
  }

  private pluckGayageumNote(
    ctx: AudioContext,
    freq: number,
    startTime: number,
    volume: number
  ): void {
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const filter = ctx.createBiquadFilter();
    const gain = ctx.createGain();

    osc1.type = 'triangle';
    osc2.type = 'sine';
    // Slight Korean string vibrato (Nonghyeon)
    osc1.frequency.setValueAtTime(freq * 1.004, startTime);
    osc1.frequency.exponentialRampToValueAtTime(freq, startTime + 0.08);
    osc2.frequency.setValueAtTime(freq * 2, startTime);

    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(1900, startTime);
    filter.frequency.exponentialRampToValueAtTime(520, startTime + 0.9);

    gain.gain.setValueAtTime(0.001, startTime);
    gain.gain.linearRampToValueAtTime(volume, startTime + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0008, startTime + 1.15);

    const g2 = ctx.createGain();
    g2.gain.value = 0.28;

    osc1.connect(filter);
    osc2.connect(g2).connect(filter);
    filter.connect(gain).connect(ctx.destination);

    osc1.start(startTime);
    osc2.start(startTime);
    osc1.stop(startTime + 1.2);
    osc2.stop(startTime + 1.2);
  }

  private stopMusicLoop(): void {
    if (this.musicTimer !== null) {
      window.clearInterval(this.musicTimer);
      this.musicTimer = null;
    }
  }

  public playUiClick(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(640, now);
    osc.frequency.exponentialRampToValueAtTime(880, now + 0.035);
    gain.gain.setValueAtTime(0.055, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.04);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.045);
  }

  public playChatPop(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(587.33, now);
    osc.frequency.exponentialRampToValueAtTime(783.99, now + 0.075);
    gain.gain.setValueAtTime(0.065, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.11);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.12);
  }

  public playJump(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(190, now);
    osc.frequency.exponentialRampToValueAtTime(360, now + 0.09);
    gain.gain.setValueAtTime(0.06, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.1);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.11);
  }

  public playQuestComplete(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const notes = [523.25, 659.25, 783.99, 1046.5];
    notes.forEach((freq, i) => {
      this.pluckGayageumNote(ctx, freq, now + i * 0.09, 0.09);
    });
  }

  public playDig(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(160 + Math.random() * 55, now);
    osc.frequency.exponentialRampToValueAtTime(75, now + 0.055);
    gain.gain.setValueAtTime(0.08, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.06);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.065);
  }

  public playBreak(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const bufferSize = Math.floor(ctx.sampleRate * 0.11);
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.exp(-i / (bufferSize * 0.35));
    }
    const noise = ctx.createBufferSource();
    noise.buffer = buffer;

    const filter = ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.value = 620 + Math.random() * 220;

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.18, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.11);
    noise.connect(filter).connect(gain).connect(ctx.destination);
    noise.start(now);
  }

  public playPlace(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(220, now);
    osc.frequency.exponentialRampToValueAtTime(340, now + 0.055);
    gain.gain.setValueAtTime(0.12, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.065);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.07);
  }

  public playPickup(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(520, now);
    osc.frequency.exponentialRampToValueAtTime(920, now + 0.08);
    gain.gain.setValueAtTime(0.1, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.09);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.095);
  }

  public playSwordSwing(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(420, now);
    osc.frequency.exponentialRampToValueAtTime(130, now + 0.11);
    gain.gain.setValueAtTime(0.09, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.125);
  }

  public playEat(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    for (let i = 0; i < 3; i++) {
      const t = now + i * 0.07;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(300 + i * 80, t);
      gain.gain.setValueAtTime(0.09, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.055);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.06);
    }
  }

  public playGreetingChime(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const notes = [523.25, 659.25, 783.99];
    notes.forEach((freq, idx) => {
      this.pluckGayageumNote(ctx, freq, now + idx * 0.07, 0.075);
    });
  }

  public playExplosion(): void {
    if (!this.sfxEnabled) return;
    const ctx = this.ensureContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    const bufferSize = Math.floor(ctx.sampleRate * 0.55);
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.exp(-i / (bufferSize * 0.28));
    }
    const noise = ctx.createBufferSource();
    noise.buffer = buffer;

    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(320, now);
    filter.frequency.exponentialRampToValueAtTime(60, now + 0.5);

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.35, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
    noise.connect(filter).connect(gain).connect(ctx.destination);
    noise.start(now);
  }
}

export const soundFX = new SoundFXManager();
