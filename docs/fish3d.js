// 🐠 Diana 3D — ماهی زنده سه‌بعدی دیانا در آکواریوم تعاملی (Three.js)
// دیانا شنا می‌کنه، دنبال اشاره‌گر میاد، غذا می‌خوره، موقع حرف‌زدن دهنش تکون می‌خوره و حباب می‌سازه،
// و ماهی‌های کوچیکِ همراهش نماینده ۱۲ دپارتمان ایجنت‌ها هستن که موقع کار هر دپارتمان می‌درخشن.
import * as THREE from 'three';

const DEPT_COLORS = ["#22d3ee","#a78bfa","#f472b6","#34d399","#fb923c","#facc15",
                     "#f87171","#60a5fa","#4ade80","#94a3b8","#c084fc","#38bdf8"];

export function initDianaFish(canvas, wrap) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x07406a);
  scene.fog = new THREE.Fog(0x07406a, 12, 30);
  const camera = new THREE.PerspectiveCamera(48, 16 / 10, 0.1, 100);
  camera.position.set(0, 1.1, 10.5);
  camera.lookAt(0, 0.2, 0);

  scene.add(new THREE.AmbientLight(0x9fd8ff, 0.85));
  const sun = new THREE.DirectionalLight(0xfff2cc, 1.6);
  sun.position.set(4, 8, 5);
  scene.add(sun);
  const glowCyan = new THREE.PointLight(0x22d3ee, 12, 20); glowCyan.position.set(-5, 2, 3); scene.add(glowCyan);
  const glowGold = new THREE.PointLight(0xfbbf24, 6, 16); glowGold.position.set(5, 3, 2); scene.add(glowGold);

  // ---------- بافت بدن ماهی (دلقک‌ماهی طلایی) ----------
  function bodyTexture() {
    const c = document.createElement('canvas'); c.width = 512; c.height = 256;
    const x = c.getContext('2d');
    const g = x.createLinearGradient(0, 0, 0, 256);
    g.addColorStop(0, '#ff9d2e'); g.addColorStop(0.5, '#ff7b00'); g.addColorStop(1, '#ffb347');
    x.fillStyle = g; x.fillRect(0, 0, 512, 256);
    // نوارهای سفید دلقک‌ماهی (بعد از چرخش کره، حلقه دور بدن می‌شن)
    x.fillStyle = 'rgba(60,20,0,0.55)';
    [52, 128, 196].forEach(y => x.fillRect(0, y - 3, 512, 30));
    x.fillStyle = '#fff7ea';
    [52, 128, 196].forEach(y => x.fillRect(0, y, 512, 24));
    // درخشش طلایی
    const rg = x.createRadialGradient(256, 110, 20, 256, 110, 260);
    rg.addColorStop(0, 'rgba(255,230,150,0.35)'); rg.addColorStop(1, 'rgba(255,255,255,0)');
    x.fillStyle = rg; x.fillRect(0, 0, 512, 256);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  }
  function finShape(len, wid) {
    const s = new THREE.Shape();
    s.moveTo(0, 0);
    s.quadraticCurveTo(-len * 0.7, wid, -len, wid * 0.55);
    s.quadraticCurveTo(-len * 0.78, 0, -len, -wid * 0.55);
    s.quadraticCurveTo(-len * 0.7, -wid, 0, 0);
    return new THREE.ShapeGeometry(s, 12);
  }

  // ---------- ساخت دیانا ----------
  const Diana = new THREE.Group();
  const bodyGeo = new THREE.SphereGeometry(1, 48, 32);
  bodyGeo.rotateZ(Math.PI / 2);           // قطب‌ها به سر و دم
  bodyGeo.scale(1.55, 1.02, 0.72);
  const body = new THREE.Mesh(bodyGeo, new THREE.MeshStandardMaterial({
    map: bodyTexture(), roughness: 0.35, metalness: 0.15,
    emissive: 0xff7b00, emissiveIntensity: 0.06 }));
  Diana.add(body);

  const finMat = new THREE.MeshStandardMaterial({ color: 0xffa03c, roughness: 0.5,
    transparent: true, opacity: 0.92, side: THREE.DoubleSide, emissive: 0xff8c1a, emissiveIntensity: 0.25 });
  const tailPivot = new THREE.Group(); tailPivot.position.set(-1.45, 0, 0);
  tailPivot.add(new THREE.Mesh(finShape(1.15, 0.85), finMat)); Diana.add(tailPivot);
  const dorsal = new THREE.Mesh(finShape(0.95, 0.4), finMat);
  dorsal.position.set(0.15, 0.92, 0); dorsal.rotation.z = 0.9; Diana.add(dorsal);
  const finL = new THREE.Mesh(finShape(0.62, 0.4), finMat);
  finL.position.set(0.55, -0.35, 0.62); finL.rotation.set(0.5, 0.4, 0.5); Diana.add(finL);
  const finR = new THREE.Mesh(finShape(0.62, 0.4), finMat);
  finR.position.set(0.55, -0.35, -0.62); finR.rotation.set(-0.5, -0.4, 0.5); Diana.add(finR);

  // چشم‌ها
  const pupils = [];
  function makeEye(zSide) {
    const g = new THREE.Group();
    const white = new THREE.Mesh(new THREE.SphereGeometry(0.19, 20, 16),
      new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.25 }));
    const pupil = new THREE.Mesh(new THREE.SphereGeometry(0.105, 16, 12),
      new THREE.MeshStandardMaterial({ color: 0x1a1005, roughness: 0.2 }));
    pupil.position.set(0.1, 0.02, zSide * 0.1);
    const shine = new THREE.Mesh(new THREE.SphereGeometry(0.04, 8, 8),
      new THREE.MeshBasicMaterial({ color: 0xffffff }));
    shine.position.set(0.16, 0.09, zSide * 0.14);
    g.add(white, pupil, shine);
    g.position.set(1.08, 0.34, zSide * 0.5);
    pupils.push(pupil);
    return g;
  }
  Diana.add(makeEye(1), makeEye(-1));

  // دهان
  const mouth = new THREE.Mesh(new THREE.CircleGeometry(0.13, 20),
    new THREE.MeshStandardMaterial({ color: 0x8a3324, roughness: 0.6 }));
  mouth.position.set(1.56, -0.12, 0); mouth.rotation.y = Math.PI / 2; Diana.add(mouth);

  // گونه‌های سرخ
  const blushMat = new THREE.MeshBasicMaterial({ color: 0xff8fab, transparent: true, opacity: 0.55 });
  [1, -1].forEach(s => {
    const b = new THREE.Mesh(new THREE.CircleGeometry(0.13, 16), blushMat);
    b.position.set(1.05, -0.05, s * 0.66); b.rotation.y = s * 1.15; Diana.add(b);
  });

  // تاج طلایی ملکه دیانا 👑
  const crown = new THREE.Group();
  const goldMat = new THREE.MeshStandardMaterial({ color: 0xffd54a, metalness: 0.85, roughness: 0.25, emissive: 0xaa7a00, emissiveIntensity: 0.35 });
  crown.add(new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.36, 0.22, 20, 1, true), goldMat));
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    const spike = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.24, 8), goldMat);
    spike.position.set(Math.cos(a) * 0.3, 0.2, Math.sin(a) * 0.3);
    const gem = new THREE.Mesh(new THREE.SphereGeometry(0.045, 8, 8),
      new THREE.MeshBasicMaterial({ color: i % 2 ? 0xff4d6d : 0x22d3ee }));
    gem.position.set(Math.cos(a) * 0.3, 0.34, Math.sin(a) * 0.3);
    crown.add(spike, gem);
  }
  crown.position.set(0.52, 1.05, 0); crown.rotation.z = -0.14;
  Diana.add(crown);
  Diana.position.set(0, 0.4, 0);
  scene.add(Diana);

  // ---------- ماهی‌های همراه = ۱۲ دپارتمان ایجنت‌ها ----------
  const companions = [];
  DEPT_COLORS.forEach((col, i) => {
    const g = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({ color: col, roughness: 0.4, emissive: col, emissiveIntensity: 0.15 });
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.22, 14, 10), mat);
    b.scale.set(1.7, 0.9, 0.6);
    const t = new THREE.Mesh(finShape(0.34, 0.26), mat); t.position.x = -0.34;
    g.add(b, t);
    g.userData = { mat, tail: t, phase: i * 1.7, radius: 3 + (i % 4), height: -1 + (i % 5) * 0.7,
                   speed: 0.25 + (i % 3) * 0.07, pulse: 0, color: col.toLowerCase() };
    scene.add(g); companions.push(g);
  });

  // ---------- محیط آکواریوم ----------
  const sand = new THREE.Mesh(new THREE.CircleGeometry(16, 40),
    new THREE.MeshStandardMaterial({ color: 0xc2a878, roughness: 1 }));
  sand.rotation.x = -Math.PI / 2; sand.position.y = -2.9; scene.add(sand);
  const rockMat = new THREE.MeshStandardMaterial({ color: 0x5b6b7a, roughness: 0.95, flatShading: true });
  [[-4.5, -2.6, -1.5, 1.1], [4.2, -2.7, -2, 0.9], [2.5, -2.75, -3.4, 0.6], [-2, -2.8, -3.6, 0.8]].forEach(([x, y, z, s]) => {
    const r = new THREE.Mesh(new THREE.DodecahedronGeometry(s, 0), rockMat);
    r.position.set(x, y, z); r.rotation.set(x, z, y); scene.add(r);
  });
  const coralCols = [0xff6b9d, 0xff8c42, 0xc084fc, 0xff5d5d];
  [[-3.6, -2.4], [3.4, -1.2], [-5.2, 0.6], [5.4, 0.2]].forEach(([x, z], ci) => {
    for (let j = 0; j < 5; j++) {
      const m = new THREE.Mesh(new THREE.IcosahedronGeometry(0.16 + Math.random() * 0.16, 0),
        new THREE.MeshStandardMaterial({ color: coralCols[ci], roughness: 0.7, flatShading: true, emissive: coralCols[ci], emissiveIntensity: 0.12 }));
      m.position.set(x + (Math.random() - 0.5) * 0.8, -2.75 + Math.random() * 0.35, z + (Math.random() - 0.5) * 0.8);
      scene.add(m);
    }
  });
  const weeds = [];
  const weedMat = new THREE.MeshStandardMaterial({ color: 0x2ea86a, roughness: 0.8, side: THREE.DoubleSide });
  for (let i = 0; i < 14; i++) {
    const pivot = new THREE.Group();
    const h = 1.4 + Math.random() * 1.6;
    const blade = new THREE.Mesh(new THREE.PlaneGeometry(0.16, h, 1, 4), weedMat);
    blade.position.y = h / 2;
    pivot.add(blade);
    pivot.position.set(-6.5 + i * 1.0 + Math.random() * 0.5, -2.9, -2.5 + Math.random() * 2.2);
    pivot.userData.phase = Math.random() * 6;
    scene.add(pivot); weeds.push(pivot);
  }
  // پرتوهای نور
  const rays = [];
  [[-3, 0.35], [0.5, 0.2], [3.5, 0.45]].forEach(([x, tilt]) => {
    const ray = new THREE.Mesh(new THREE.ConeGeometry(1.6, 11, 20, 1, true),
      new THREE.MeshBasicMaterial({ color: 0xbfe9ff, transparent: true, opacity: 0.05, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
    ray.position.set(x, 3.6, -1.5); ray.rotation.z = tilt; scene.add(ray); rays.push(ray);
  });
  // پلانکتون‌های شناور
  const pGeo = new THREE.BufferGeometry();
  const pCount = 260, pPos = new Float32Array(pCount * 3);
  for (let i = 0; i < pCount; i++) { pPos[i*3] = (Math.random()-0.5)*16; pPos[i*3+1] = (Math.random()-0.5)*7; pPos[i*3+2] = (Math.random()-0.5)*7; }
  pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3));
  const plankton = new THREE.Points(pGeo, new THREE.PointsMaterial({ color: 0xd6f4ff, size: 0.05, transparent: true, opacity: 0.75 }));
  scene.add(plankton);
  // حباب‌های محیطی
  const bubCount = 50;
  const bubbles = new THREE.InstancedMesh(new THREE.SphereGeometry(0.06, 10, 8),
    new THREE.MeshStandardMaterial({ color: 0xcfeeff, transparent: true, opacity: 0.5, roughness: 0.1 }), bubCount);
  const bubData = Array.from({ length: bubCount }, () => ({ x: (Math.random()-0.5)*14, y: -3 + Math.random()*6.5, z: (Math.random()-0.5)*5, s: 0.5 + Math.random()*1.4, v: 0.3 + Math.random()*0.6 }));
  scene.add(bubbles);
  // حباب‌های حرف‌زدن از دهان دیانا
  const speechBubs = [];
  for (let i = 0; i < 16; i++) {
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.07, 10, 8),
      new THREE.MeshStandardMaterial({ color: 0xeaf9ff, transparent: true, opacity: 0.0, roughness: 0.1 }));
    b.visible = false; scene.add(b); speechBubs.push({ m: b, life: 0 });
  }

  // ---------- غذا و تعامل ----------
  const foods = [];
  const foodMat = new THREE.MeshStandardMaterial({ color: 0xffb020, emissive: 0xcc7a00, emissiveIntensity: 0.5, roughness: 0.5 });
  function spawnFood(x, y, z) {
    const f = new THREE.Mesh(new THREE.SphereGeometry(0.11, 10, 8), foodMat);
    f.position.set(x, y, z); scene.add(f); foods.push(f);
  }
  const raycaster = new THREE.Raycaster();
  const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
  const pointerWorld = new THREE.Vector3(0, 0.4, 0);
  let pointerActive = 0;
  function toWorld(ev) {
    const r = canvas.getBoundingClientRect();
    const nd = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(nd, camera);
    const out = new THREE.Vector3();
    return raycaster.ray.intersectPlane(plane, out) ? out : null;
  }
  wrap.addEventListener('pointermove', ev => { const p = toWorld(ev); if (p) { pointerWorld.copy(p); pointerActive = 2.2; } });
  wrap.addEventListener('click', ev => {
    if (ev.target !== canvas) return;
    const p = toWorld(ev); if (p) spawnFood(THREE.MathUtils.clamp(p.x, -6, 6), THREE.MathUtils.clamp(p.y, -1.5, 3), 0);
  });

  // ---------- حالت و رفتار ----------
  let mood = 'idle', speaking = false, rollT = 0, moodTimer = 0;
  const target = new THREE.Vector3(2, 0.6, 0);
  const velocity = new THREE.Vector3(0.6, 0, 0);
  let wanderT = 0;
  const clock = new THREE.Clock();
  const dummy = new THREE.Object3D();

  function resize() {
    const w = wrap.clientWidth, h = wrap.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(wrap); resize();

  function animate() {
    requestAnimationFrame(animate);
    const dt = Math.min(clock.getDelta(), 0.05);
    const t = clock.elapsedTime;
    if (pointerActive > 0) pointerActive -= dt;
    if (moodTimer > 0) { moodTimer -= dt; if (moodTimer <= 0 && mood !== 'thinking') mood = 'idle'; }

    // انتخاب هدف حرکت
    wanderT -= dt;
    if (foods.length) target.copy(foods[0].position);
    else if (pointerActive > 0) target.lerp(pointerWorld, 0.4);
    else if (mood === 'thinking') target.set(Math.sin(t * 0.5) * 2.4, 1.5 + Math.sin(t * 0.8) * 0.3, Math.cos(t * 0.5) * 0.8);
    else if (wanderT <= 0) {
      wanderT = 2.5 + Math.random() * 3;
      target.set((Math.random() - 0.5) * 10, -1.2 + Math.random() * 3.2, (Math.random() - 0.5) * 2.6);
    }
    target.x = THREE.MathUtils.clamp(target.x, -6, 6);
    target.y = THREE.MathUtils.clamp(target.y, -1.8, 2.8);
    target.z = THREE.MathUtils.clamp(target.z, -2.2, 2.2);

    const speedBase = foods.length ? 3.4 : mood === 'excited' ? 2.5 : mood === 'thinking' ? 0.9 : 1.5;
    const desired = new THREE.Vector3().subVectors(target, Diana.position);
    const dist = desired.length();
    desired.normalize().multiplyScalar(Math.min(speedBase, dist * 1.6));
    velocity.lerp(desired, 1 - Math.pow(0.0015, dt));
    Diana.position.addScaledVector(velocity, dt);
    Diana.position.y += Math.sin(t * 2.1) * 0.0018;

    // جهت و موج بدن
    if (velocity.lengthSq() > 0.002) {
      const yaw = Math.atan2(-velocity.z, velocity.x);
      const pitch = THREE.MathUtils.clamp(Math.asin(velocity.y / (velocity.length() + 1e-5)) * 0.7, -0.5, 0.5);
      Diana.rotation.y += (((yaw - Diana.rotation.y + Math.PI * 3) % (Math.PI * 2)) - Math.PI) * Math.min(1, dt * 6);
      Diana.rotation.z = Math.cos(Diana.rotation.y) >= 0 ? pitch : -pitch;
      if (rollT > 0) { rollT -= dt; Diana.rotation.x = Math.sin((1 - Math.max(rollT, 0)) * Math.PI) * Math.PI * 2 * 1; }
      else Diana.rotation.x *= 0.9;
    }
    const spd = velocity.length();
    const wag = 5 + spd * 3.2 + (speaking ? 3 : 0);
    tailPivot.rotation.y = Math.sin(t * wag) * (0.35 + spd * 0.12);
    body.rotation.y = Math.sin(t * wag - 0.6) * 0.07;
    finL.rotation.x = 0.5 + Math.sin(t * (wag * 0.8)) * 0.45;
    finR.rotation.x = -0.5 - Math.sin(t * (wag * 0.8)) * 0.45;
    dorsal.rotation.x = Math.sin(t * wag * 0.6) * 0.14;
    crown.rotation.z = -0.14 + Math.sin(t * 2.2) * 0.045;

    // نگاه چشم‌ها به سمت هدف
    pupils.forEach(p => { p.position.x = 0.1 + THREE.MathUtils.clamp(velocity.x * 0.02, -0.03, 0.05); p.position.y = 0.02 + THREE.MathUtils.clamp(velocity.y * 0.03, -0.04, 0.04); });

    // دهان و حباب حرف‌زدن
    if (speaking) {
      const s = 1 + Math.sin(t * 17) * 0.55;
      mouth.scale.set(1, Math.max(0.25, s), 1);
      if (Math.random() < dt * 7) {
        const slot = speechBubs.find(b => b.life <= 0);
        if (slot) {
          const mp = new THREE.Vector3(1.7, -0.1, 0).applyEuler(Diana.rotation).add(Diana.position);
          slot.m.position.copy(mp); slot.m.visible = true; slot.life = 1.6; slot.m.material.opacity = 0.85;
          slot.m.scale.setScalar(0.6 + Math.random());
        }
      }
    } else mouth.scale.y += (0.55 - mouth.scale.y) * dt * 8;
    speechBubs.forEach(b => {
      if (b.life > 0) { b.life -= dt; b.m.position.y += dt * 1.1; b.m.position.x += Math.sin(t * 6 + b.m.position.y * 4) * dt * 0.25; b.m.material.opacity = Math.min(0.85, b.life); if (b.life <= 0) b.m.visible = false; }
    });

    // غذا: غرق‌شدن و خورده‌شدن
    for (let i = foods.length - 1; i >= 0; i--) {
      const f = foods[i];
      f.position.y -= dt * 0.35;
      f.rotation.y += dt * 3;
      if (f.position.distanceTo(Diana.position) < 1.15) {
        scene.remove(f); foods.splice(i, 1);
        mood = 'excited'; moodTimer = 1.6; rollT = 0.9;
        mouth.scale.set(1.4, 1.4, 1);
      } else if (f.position.y < -2.75) { scene.remove(f); foods.splice(i, 1); }
    }

    // ماهی‌های همراه (دپارتمان‌ها)
    companions.forEach((c, i) => {
      const u = c.userData;
      const a = t * u.speed + u.phase;
      const cx = Math.cos(a) * u.radius, cz = Math.sin(a) * 1.4 - 0.6;
      const cy = u.height + Math.sin(t * 0.9 + u.phase) * 0.3;
      const prev = c.position.clone();
      c.position.set(cx, cy, cz);
      const d = new THREE.Vector3().subVectors(c.position, prev);
      if (d.lengthSq() > 1e-8) c.rotation.y = Math.atan2(-d.z, d.x);
      u.tail.rotation.y = Math.sin(t * 7 + u.phase) * 0.5;
      if (u.pulse > 0) { u.pulse -= dt; u.mat.emissiveIntensity = 0.15 + Math.max(0, u.pulse) * 1.6; c.scale.setScalar(1 + Math.max(0, u.pulse) * 0.35); }
    });

    // محیط
    weeds.forEach(w => { w.rotation.z = Math.sin(t * 1.1 + w.userData.phase) * 0.13; });
    rays.forEach((r, i) => { r.material.opacity = 0.04 + Math.sin(t * 0.5 + i * 2) * 0.02; });
    plankton.rotation.y = t * 0.012;
    bubData.forEach((b, i) => {
      b.y += b.v * dt; if (b.y > 3.6) b.y = -2.9;
      dummy.position.set(b.x + Math.sin(t * 2 + i) * 0.08, b.y, b.z);
      dummy.scale.setScalar(b.s); dummy.updateMatrix();
      bubbles.setMatrixAt(i, dummy.matrix);
    });
    bubbles.instanceMatrix.needsUpdate = true;
    glowGold.intensity = mood === 'thinking' ? 15 : 6 + Math.sin(t * 1.4) * 2;
    body.material.emissiveIntensity = mood === 'thinking' ? 0.22 : speaking ? 0.14 : 0.06;
    camera.position.x = Math.sin(t * 0.07) * 0.5;
    camera.lookAt(0, 0.2, 0);

    renderer.render(scene, camera);
  }
  animate();

  return {
    say() { mood = 'excited'; moodTimer = 2; },
    setSpeaking(v) { speaking = !!v; },
    setMood(m) {
      mood = m;
      if (m === 'excited' || m === 'celebrate') { rollT = 0.9; moodTimer = 2.4; mood = 'excited'; }
      if (m === 'thinking') moodTimer = 9999;
      if (m === 'idle') moodTimer = 0;
    },
    pulseDept(color) {
      const c = companions.find(x => x.userData.color === String(color).toLowerCase());
      if (c) c.userData.pulse = 2.2;
    },
    feed() { spawnFood((Math.random() - 0.5) * 6, 2.4, 0); },
  };
}
