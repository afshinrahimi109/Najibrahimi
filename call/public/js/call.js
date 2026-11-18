/*
 * موتور تماس — پیاده‌سازی WebRTC
 * ──────────────────────────────────────────────────────────────
 * نکته‌ی مهم معماری: هر دو طرف از ابتدا دو «ترنسکیور» (صدا و تصویر)
 * با جهت sendrecv می‌سازند و بعد فقط با replaceTrack ترک‌ها را عوض
 * می‌کنند. نتیجه: روشن/خاموش کردن میکروفون و دوربین در میانه‌ی تماس
 * هیچ مذاکره‌ی مجددی لازم ندارد و تماس قطع نمی‌شود.
 */

export function friendlyMediaError(err) {
  const name = err?.name || '';
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'دسترسی به میکروفون/دوربین داده نشد. اگر این صفحه داخل قاب (iframe) باز است، آن را در تب جدا باز کن و اجازه بده.';
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return 'میکروفون یا دوربینی روی این دستگاه پیدا نشد.';
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return 'میکروفون در اختیار برنامه‌ی دیگری است. برنامه‌های دیگر (تماس، ضبط صدا) را ببند و دوباره تلاش کن.';
  }
  if (name === 'OverconstrainedError') {
    return 'دستگاه انتخاب‌شده در دسترس نیست؛ دستگاه پیش‌فرض را امتحان کن.';
  }
  if (!window.isSecureContext) {
    return 'مرورگرها فقط روی HTTPS اجازه‌ی میکروفون می‌دهند. این صفحه را با https باز کن.';
  }
  return err?.message || 'دسترسی به میکروفون ممکن نشد.';
}

const AUDIO_CONSTRAINTS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  channelCount: 1,
  sampleRate: 48000,
};

export class LiveCall {
  constructor({ iceServers = [], settings = {}, callbacks = {} } = {}) {
    this.iceServers = iceServers;
    this.settings = settings;
    this.cb = callbacks;
    this.pc = null;
    this.localStream = new MediaStream();
    this.remoteStream = new MediaStream();
    this.micTrack = null;
    this.camTrack = null;
    this.audioTx = null;
    this.videoTx = null;
    this.isInitiator = false;
    this.closed = false;
    this.negotiated = false;
    this.pendingRemoteCandidates = [];
    this.sendQueue = [];
    this.audioCtx = null;
    this.analyser = null;
    this.levelBuf = null;
    this.levelSmooth = 0;
    this.prevStats = null;
    this.facing = settings.facing || 'user';
  }

  emitSignal(data) {
    if (this.closed) return;
    this.cb.onSignal?.(data);
  }

  /* ───────────── رسانه ───────────── */

  async openMic() {
    if (this.micTrack && this.micTrack.readyState === 'live') return this.micTrack;
    const audio = { ...AUDIO_CONSTRAINTS };
    if (this.settings.micId) audio.deviceId = { exact: this.settings.micId };
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio, video: false });
    } catch (err) {
      if (err.name === 'OverconstrainedError') {
        stream = await navigator.mediaDevices.getUserMedia({ audio: AUDIO_CONSTRAINTS, video: false });
      } else {
        throw err;
      }
    }
    this.micTrack = stream.getAudioTracks()[0] || null;
    if (this.micTrack) {
      this.localStream.addTrack(this.micTrack);
      this.micTrack.onended = () => this.cb.onTracksChanged?.();
    }
    this.cb.onTracksChanged?.();
    return this.micTrack;
  }

  async openCamera(facing) {
    const base = {
      width: { ideal: 1280 },
      height: { ideal: 720 },
      frameRate: { ideal: 30, max: 30 },
    };
    if (this.settings.camId) base.deviceId = { exact: this.settings.camId };
    else base.facingMode = { ideal: facing || this.facing };

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: base });
    } catch (err) {
      if (err.name === 'OverconstrainedError') {
        stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: true });
      } else {
        throw err;
      }
    }
    const track = stream.getVideoTracks()[0] || null;
    if (!track) throw new Error('دوربین در دسترس نیست.');
    this.setCameraTrack(track);
    return track;
  }

  setCameraTrack(track) {
    const old = this.camTrack;
    if (old && old !== track) {
      this.localStream.removeTrack(old);
      try { old.stop(); } catch { /* noop */ }
    }
    this.camTrack = track;
    if (track) {
      this.localStream.addTrack(track);
      track.onended = () => this.cb.onTracksChanged?.();
    }
    if (this.videoTx) {
      this.videoTx.sender.replaceTrack(track || null).catch(() => {});
      // اگر در مذاکره‌ی قبلی جهت این ترنسکیور «فقط دریافت» بود،
      // برای فرستادن تصویر یک بار دیگر مذاکره لازم است
      if (track && this.videoTx.direction === 'recvonly') this.requestRenegotiation();
    }
    this.cb.onTracksChanged?.();
  }

  get micOn() { return Boolean(this.micTrack && this.micTrack.enabled && this.micTrack.readyState === 'live'); }
  get camOn() { return Boolean(this.camTrack && this.camTrack.enabled && this.camTrack.readyState === 'live'); }

  setMicEnabled(on) {
    if (this.micTrack) this.micTrack.enabled = on;
    this.announceMedia();
  }

  async setCameraEnabled(on) {
    if (on) {
      if (!this.camTrack) await this.openCamera(this.facing);
      if (this.camTrack) this.camTrack.enabled = true;
      if (!this.videoTx) {
        await this.requestRenegotiation();
      } else {
        this.videoTx.sender.replaceTrack(this.camTrack).catch(() => {});
      }
    } else {
      if (this.camTrack) this.camTrack.enabled = false;
      if (this.videoTx) this.videoTx.sender.replaceTrack(null).catch(() => {});
    }
    this.announceMedia();
  }

  announceMedia() {
    this.emitSignal({ media: { mic: this.micOn, cam: this.camOn } });
  }

  /* ───────────── اتصال ───────────── */

  createPeer() {
    if (this.pc) return this.pc;
    const pc = new RTCPeerConnection({
      iceServers: this.iceServers,
      bundlePolicy: 'max-bundle',
      rtcpMuxPolicy: 'require',
      iceCandidatePoolSize: 2,
    });
    this.pc = pc;

    pc.onicecandidate = (e) => {
      if (e.candidate) this.emitSignal({ candidate: e.candidate.toJSON() });
    };

    pc.ontrack = (e) => {
      const track = e.track;
      if (!this.remoteStream.getTracks().includes(track)) {
        this.remoteStream.addTrack(track);
      }
      track.addEventListener('unmute', () => this.cb.onRemoteStream?.(this.remoteStream));
      track.addEventListener('ended', () => this.cb.onRemoteStream?.(this.remoteStream));
      this.cb.onRemoteStream?.(this.remoteStream);
      this.setupAnalyser();
    };

    pc.onconnectionstatechange = () => {
      this.cb.onConnectionState?.(pc.connectionState);
      if (pc.connectionState === 'connected') this.setupAnalyser();
    };

    pc.oniceconnectionstatechange = () => {
      this.cb.onIceState?.(pc.iceConnectionState);
    };

    return pc;
  }

  async startAsCaller() {
    this.isInitiator = true;
    const pc = this.createPeer();

    this.audioTx = pc.addTransceiver(this.micTrack || 'audio', {
      direction: 'sendrecv',
      ...(this.micTrack ? { streams: [this.localStream] } : {}),
    });
    this.videoTx = pc.addTransceiver(this.camTrack || 'video', {
      direction: 'sendrecv',
      ...(this.camTrack ? { streams: [this.localStream] } : {}),
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    this.emitSignal({ sdp: { type: 'offer', sdp: pc.localDescription.sdp } });
    this.flushCandidates();
  }

  /**
   * طرف پاسخ‌دهنده: پیشنهاد را می‌گیرد، ترک‌های خودش را وصل می‌کند و جواب می‌دهد.
   * (اگر پیشنهاد دوباره بیاید — مثلاً برای روشن کردن دوربین — همین تابع دوباره اجرا می‌شود.)
   */
  async handleSignal(data) {
    if (this.closed || !data) return;

    if (data.request === 'renegotiate') {
      if (this.isInitiator) await this.makeOffer({ iceRestart: false });
      return;
    }
    if (data.request === 'restart') {
      if (this.isInitiator) await this.makeOffer({ iceRestart: true });
      return;
    }
    if (data.media) {
      this.cb.onPeerMedia?.(data.media);
      return;
    }

    const pc = this.createPeer();

    if (data.candidate) {
      const cand = data.candidate;
      if (pc.remoteDescription) {
        try { await pc.addIceCandidate(cand); } catch { /* نامزد تکراری/قدیمی */ }
      } else {
        this.pendingRemoteCandidates.push(cand);
      }
      return;
    }

    if (!data.sdp) return;
    const desc = { type: data.sdp.type, sdp: data.sdp.sdp };

    if (desc.type === 'offer') {
      await pc.setRemoteDescription(desc);

      // ترک‌های محلی را روی ترنسکیورهای موجود سوار کن (بدون مذاکره‌ی مجدد)
      for (const tx of pc.getTransceivers()) {
        const kind = tx.receiver?.track?.kind || tx.sender?.track?.kind;
        const local = kind === 'audio' ? this.micTrack : kind === 'video' ? this.camTrack : null;
        try {
          tx.direction = local ? 'sendrecv' : 'recvonly';
          if (local) await tx.sender.replaceTrack(local);
          if (kind === 'audio') this.audioTx = tx;
          if (kind === 'video') this.videoTx = tx;
        } catch { /* ترنسکیور قفل‌شده را رد کن */ }
      }

      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      this.emitSignal({ sdp: { type: 'answer', sdp: pc.localDescription.sdp } });
      this.negotiated = true;
      this.flushCandidates();
      return;
    }

    if (desc.type === 'answer') {
      if (pc.signalingState !== 'have-local-offer') return;
      await pc.setRemoteDescription(desc);
      this.negotiated = true;
      this.flushCandidates();
    }
  }

  async makeOffer({ iceRestart = false } = {}) {
    if (!this.pc || this.closed) return;
    try {
      if (iceRestart) this.pc.restartIce();
      const offer = await this.pc.createOffer({ iceRestart });
      await this.pc.setLocalDescription(offer);
      this.emitSignal({ sdp: { type: 'offer', sdp: this.pc.localDescription.sdp } });
    } catch { /* اگر مذاکره شکست خورد، تماس فعلی ادامه دارد */ }
  }

  async requestRenegotiation() {
    if (this.isInitiator) return this.makeOffer({ iceRestart: false });
    this.emitSignal({ request: 'renegotiate' });
  }

  async restartIce() {
    if (this.isInitiator) return this.makeOffer({ iceRestart: true });
    this.emitSignal({ request: 'restart' });
  }

  async flushCandidates() {
    if (!this.pc) return;
    const list = this.pendingRemoteCandidates.splice(0);
    for (const c of list) {
      try { await this.pc.addIceCandidate(c); } catch { /* noop */ }
    }
  }

  /* ───────────── سطح صدا، آمار و پایان ───────────── */

  setupAnalyser() {
    if (this.analyser || !this.remoteStream.getAudioTracks().length) return;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      this.audioCtx = this.audioCtx || new Ctx();
      if (this.audioCtx.state === 'suspended') this.audioCtx.resume().catch(() => {});
      const src = this.audioCtx.createMediaStreamSource(this.remoteStream);
      const analyser = this.audioCtx.createAnalyser();
      analyser.fftSize = 512;
      const silent = this.audioCtx.createGain();
      silent.gain.value = 0;
      src.connect(analyser);
      analyser.connect(silent);
      silent.connect(this.audioCtx.destination);
      this.analyser = analyser;
      this.levelBuf = new Uint8Array(analyser.fftSize);
    } catch { /* iOS قدیمی */ }
  }

  /** سطح صدای طرف مقابل بین ۰ تا ۱ */
  sampleLevel() {
    if (!this.analyser) return 0;
    try {
      this.analyser.getByteTimeDomainData(this.levelBuf);
      let sum = 0;
      for (let i = 0; i < this.levelBuf.length; i++) {
        const v = (this.levelBuf[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / this.levelBuf.length);
      const target = Math.min(1, rms * 3.4);
      this.levelSmooth = this.levelSmooth * 0.72 + target * 0.28;
      return this.levelSmooth;
    } catch {
      return 0;
    }
  }

  async collectStats() {
    if (!this.pc) return null;
    let report;
    try { report = await this.pc.getStats(); } catch { return null; }

    const out = { kbpsIn: 0, kbpsOut: 0, rtt: null, loss: 0, jitter: 0, codec: '', localType: '', remoteType: '' };
    let pair = null;
    let inAudio = null;
    let outAudio = null;
    let codecs = {};

    report.forEach((r) => {
      if (r.type === 'candidate-pair' && (r.selected || r.nominated) && r.state === 'succeeded') pair = r;
      if (r.type === 'inbound-rtp' && r.kind === 'audio') inAudio = r;
      if (r.type === 'outbound-rtp' && r.kind === 'audio') outAudio = r;
      if (r.type === 'codec') codecs[r.id] = r.mimeType;
    });

    if (pair) {
      const local = report.get(pair.localCandidateId);
      const remote = report.get(pair.remoteCandidateId);
      out.localType = local?.candidateType || '';
      out.remoteType = remote?.candidateType || '';
      if (typeof pair.currentRoundTripTime === 'number') out.rtt = Math.round(pair.currentRoundTripTime * 1000);
    }

    if (inAudio) {
      out.jitter = Math.round((inAudio.jitter || 0) * 1000);
      const received = inAudio.packetsReceived || 0;
      const lost = inAudio.packetsLost || 0;
      out.loss = received + lost > 0 ? +((lost / (received + lost)) * 100).toFixed(1) : 0;
      if (inAudio.codecId && codecs[inAudio.codecId]) out.codec = codecs[inAudio.codecId].split('/')[1] || '';
    }

    const now = performance.now();
    if (this.prevStats) {
      const dt = (now - this.prevStats.t) / 1000;
      if (dt > 0.4) {
        const bytesIn = (inAudio?.bytesReceived || 0) - this.prevStats.in;
        const bytesOut = (outAudio?.bytesSent || 0) - this.prevStats.out;
        out.kbpsIn = Math.max(0, Math.round((bytesIn * 8) / dt / 1000));
        out.kbpsOut = Math.max(0, Math.round((bytesOut * 8) / dt / 1000));
      }
    }
    this.prevStats = {
      t: now,
      in: inAudio?.bytesReceived || 0,
      out: outAudio?.bytesSent || 0,
    };

    return out;
  }

  close() {
    this.closed = true;
    try { this.pc?.getSenders().forEach((s) => s.track && s.track.stop()); } catch { /* noop */ }
    try { this.pc?.close(); } catch { /* noop */ }
    for (const t of this.localStream.getTracks()) { try { t.stop(); } catch { /* noop */ } }
    try { this.audioCtx?.close(); } catch { /* noop */ }
    this.audioCtx = null;
    this.analyser = null;
    this.pc = null;
  }
}
