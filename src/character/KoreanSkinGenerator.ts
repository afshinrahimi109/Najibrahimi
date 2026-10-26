import {
  KoreanFaceConfig,
  OutfitStyleId,
  SkinToneId,
} from '../types/game';

export type CanvasLike = HTMLCanvasElement | any;
export type CanvasFactory = (width: number, height: number) => CanvasLike;

const defaultBrowserFactory: CanvasFactory = (width, height) => {
  const c = document.createElement('canvas');
  c.width = width;
  c.height = height;
  return c;
};

export interface SkinPalette {
  base: string;
  highlight: string;
  midShadow: string;
  deepShadow: string;
  earInner: string;
  blushRgb: [number, number, number];
}

export const SKIN_PALETTES: Record<SkinToneId, SkinPalette> = {
  porcelain: {
    base: '#FCE3D2',
    highlight: '#FFF4EC',
    midShadow: '#ECC3AC',
    deepShadow: '#D7A389',
    earInner: '#E5AA94',
    blushRgb: [244, 132, 142],
  },
  warm_ivory: {
    base: '#F8D7BE',
    highlight: '#FFEDE0',
    midShadow: '#E5B798',
    deepShadow: '#CE9878',
    earInner: '#DE9F86',
    blushRgb: [238, 124, 128],
  },
  natural_peach: {
    base: '#F1C8AA',
    highlight: '#FBE2CE',
    midShadow: '#DBA684',
    deepShadow: '#C28968',
    earInner: '#D49178',
    blushRgb: [230, 115, 112],
  },
  honey_warm: {
    base: '#E6B794',
    highlight: '#F5D3B8',
    midShadow: '#CE9671',
    deepShadow: '#B47B57',
    earInner: '#C68368',
    blushRgb: [218, 105, 98],
  },
  dokkaebi_bronze: {
    base: '#D99E79',
    highlight: '#ECBE9E',
    midShadow: '#BD7E59',
    deepShadow: '#995E3E',
    earInner: '#B46E52',
    blushRgb: [205, 84, 78],
  },
};

function shadeHex(hex: string, amt: number): string {
  const clean = hex.replace('#', '');
  const num = parseInt(clean, 16);
  const r = Math.min(255, Math.max(0, ((num >> 16) & 0xff) + amt));
  const g = Math.min(255, Math.max(0, ((num >> 8) & 0xff) + amt));
  const b = Math.min(255, Math.max(0, (num & 0xff) + amt));
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
}

export interface GeneratedCharacterCanvases {
  headFront: CanvasLike;
  headFrontBlink: CanvasLike;
  headLeft: CanvasLike;
  headRight: CanvasLike;
  headBack: CanvasLike;
  headTop: CanvasLike;
  headBottom: CanvasLike;
  torsoFront: CanvasLike;
  torsoBack: CanvasLike;
  torsoSide: CanvasLike;
  armSkin: CanvasLike;
  legSkin: CanvasLike;
}

export function generateKoreanCharacterCanvases(
  config: KoreanFaceConfig,
  createCanvas: CanvasFactory = defaultBrowserFactory
): GeneratedCharacterCanvases {
  const headFront = drawHeadFront(config, false, createCanvas);
  const headFrontBlink = drawHeadFront(config, true, createCanvas);
  const headLeft = drawHeadSide(config, 'left', createCanvas);
  const headRight = drawHeadSide(config, 'right', createCanvas);
  const headBack = drawHeadBack(config, createCanvas);
  const headTop = drawHeadTop(config, createCanvas);
  const headBottom = drawHeadBottom(config, createCanvas);

  const torsoFront = drawTorso(config.outfitStyle, config.skinTone, 'front', createCanvas);
  const torsoBack = drawTorso(config.outfitStyle, config.skinTone, 'back', createCanvas);
  const torsoSide = drawTorso(config.outfitStyle, config.skinTone, 'side', createCanvas);
  const armSkin = drawArm(config.outfitStyle, config.skinTone, createCanvas);
  const legSkin = drawLeg(config.outfitStyle, config.skinTone, createCanvas);

  return {
    headFront,
    headFrontBlink,
    headLeft,
    headRight,
    headBack,
    headTop,
    headBottom,
    torsoFront,
    torsoBack,
    torsoSide,
    armSkin,
    legSkin,
  };
}

function drawHeadFront(
  config: KoreanFaceConfig,
  blink: boolean,
  createCanvas: CanvasFactory
): CanvasLike {
  const S = 256;
  const canvas = createCanvas(S, S);
  const ctx = canvas.getContext('2d');
  const pal = SKIN_PALETTES[config.skinTone];

  // 1. Base Korean glass-skin gradient
  const skinGrad = ctx.createLinearGradient(0, 20, 0, S);
  skinGrad.addColorStop(0, pal.highlight);
  skinGrad.addColorStop(0.45, pal.base);
  skinGrad.addColorStop(0.88, pal.base);
  skinGrad.addColorStop(1, pal.midShadow);
  ctx.fillStyle = skinGrad;
  ctx.fillRect(0, 0, S, S);

  // Subtle Minecraft voxel jawline & temple contour
  ctx.fillStyle = pal.midShadow;
  ctx.globalAlpha = 0.35;
  ctx.fillRect(0, S - 14, S, 14);
  ctx.fillRect(0, 60, 10, S - 60);
  ctx.fillRect(S - 10, 60, 10, S - 60);
  ctx.globalAlpha = 1;

  // Center forehead & T-zone K-beauty soft luminance (blended naturally with skin highlight)
  ctx.save();
  ctx.globalAlpha = 0.22;
  const tZone = ctx.createRadialGradient(128, 104, 8, 128, 114, 72);
  tZone.addColorStop(0, pal.highlight);
  tZone.addColorStop(1, 'rgba(255, 252, 248, 0)');
  ctx.fillStyle = tZone;
  ctx.fillRect(40, 40, 176, 130);
  ctx.restore();

  // 2. Soft K-Beauty Cheek Blush (볼터치) + Glass-skin highlight
  if (config.blushIntensity > 0) {
    const [br, bg, bb] = pal.blushRgb;
    for (const cx of [62, 194]) {
      const blush = ctx.createRadialGradient(cx, 170, 4, cx, 170, 38);
      blush.addColorStop(0, `rgba(${br}, ${bg}, ${bb}, ${(config.blushIntensity * 0.48).toFixed(2)})`);
      blush.addColorStop(0.65, `rgba(${br}, ${bg}, ${bb}, ${(config.blushIntensity * 0.18).toFixed(2)})`);
      blush.addColorStop(1, `rgba(${br}, ${bg}, ${bb}, 0)`);
      ctx.fillStyle = blush;
      ctx.beginPath();
      ctx.arc(cx, 170, 38, 0, Math.PI * 2);
      ctx.fill();

      // Subtle cheekbone dewy highlight (물광)
      ctx.fillStyle = 'rgba(255, 255, 255, 0.28)';
      ctx.beginPath();
      ctx.ellipse(cx + (cx < 128 ? 6 : -6), 158, 10, 4, cx < 128 ? -0.25 : 0.25, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // Elder gentle facial lines if elder
  if (config.eyeStyle === 'gentle_elder') {
    ctx.strokeStyle = pal.deepShadow;
    ctx.globalAlpha = 0.38;
    ctx.lineWidth = 2.2;
    ctx.lineCap = 'round';
    // Laugh lines (팔자주름)
    ctx.beginPath();
    ctx.moveTo(98, 180);
    ctx.quadraticCurveTo(86, 196, 90, 212);
    ctx.moveTo(158, 180);
    ctx.quadraticCurveTo(170, 196, 166, 212);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // 3. Refined Korean Nose Bridge & Soft Tip (콧대 & 코끝)
  drawNose(ctx, pal);

  // 4. Korean Lips (그라데이션 립 / 자연스러운 입술)
  drawKoreanLips(ctx, config, pal);

  // 5. Characteristic Korean Eyes (무쌍 / 속쌍 / 눈웃음 / 무사)
  drawKoreanEyePair(ctx, config, pal, blink);

  // 6. Korean Straight Eyebrows (일자 눈썹)
  drawKoreanBrows(ctx, config);

  // 7. Optional Korean Idol Beauty Mark (눈물점 / 매력점)
  if (config.beautyMark === 'under_eye') {
    ctx.fillStyle = '#3B2824';
    ctx.beginPath();
    ctx.arc(192, 154, 2.4, 0, Math.PI * 2);
    ctx.fill();
  } else if (config.beautyMark === 'cheek') {
    ctx.fillStyle = '#432E29';
    ctx.beginPath();
    ctx.arc(72, 175, 2.3, 0, Math.PI * 2);
    ctx.fill();
  }

  // 8. Front Hairline, Bangs & Traditional Headwear Bands
  drawFrontHair(ctx, config);

  // 9. Optional Painted Glasses Shadow + Rim Accent
  if (config.glasses !== 'none') {
    drawFrontGlassesOverlay(ctx, config.glasses);
  }

  return canvas;
}

function drawNose(ctx: any, pal: SkinPalette): void {
  // Luminous slim nose bridge highlight matched to skin highlight
  ctx.save();
  ctx.fillStyle = pal.highlight;
  ctx.globalAlpha = 0.42;
  ctx.beginPath();
  ctx.roundRect(124.5, 132, 7, 38, 3.5);
  ctx.fill();
  ctx.restore();

  // Subtle side nose contour
  ctx.strokeStyle = pal.midShadow;
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 2;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(121, 140);
  ctx.quadraticCurveTo(118, 166, 116, 175);
  ctx.moveTo(135, 140);
  ctx.quadraticCurveTo(138, 166, 140, 175);
  ctx.stroke();

  // Delicate nose tip shadow & nostrils
  ctx.fillStyle = pal.deepShadow;
  ctx.globalAlpha = 0.45;
  ctx.beginPath();
  ctx.ellipse(128, 178, 9, 3.2, 0, 0, Math.PI);
  ctx.fill();

  ctx.globalAlpha = 0.65;
  ctx.beginPath();
  ctx.ellipse(121, 176.5, 2.4, 1.5, 0.3, 0, Math.PI * 2);
  ctx.ellipse(135, 176.5, 2.4, 1.5, -0.3, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
}

function drawKoreanLips(ctx: any, config: KoreanFaceConfig, pal: SkinPalette): void {
  const cy = 205;
  // Soft philtrum dimple above upper lip
  ctx.fillStyle = pal.midShadow;
  ctx.globalAlpha = 0.32;
  ctx.beginPath();
  ctx.ellipse(128, 190, 4.5, 5.5, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;

  const lipPalettes: Record<
    KoreanFaceConfig['lipStyle'],
    { outer: string; inner: string; gloss: boolean }
  > = {
    natural_warm: { outer: '#DF9B8C', inner: '#C47468', gloss: false },
    kbeauty_rose: { outer: '#F09AA4', inner: '#D94B66', gloss: true },
    coral_gradient: { outer: '#F29F8E', inner: '#E0574A', gloss: true },
    berry_tint: { outer: '#EA92A4', inner: '#C63B62', gloss: true },
    elder_matte: { outer: '#D19384', inner: '#B27266', gloss: false },
  };

  const lp = lipPalettes[config.lipStyle];

  // Outer soft blurred Korean petal lip base
  ctx.save();
  ctx.fillStyle = lp.outer;
  ctx.globalAlpha = 0.78;
  ctx.beginPath();
  // Upper lip cupid's bow
  ctx.moveTo(101, cy);
  ctx.quadraticCurveTo(114, cy - 8, 123, cy - 5);
  ctx.quadraticCurveTo(128, cy - 3, 133, cy - 5);
  ctx.quadraticCurveTo(142, cy - 8, 155, cy);
  // Lower lip full curve
  ctx.quadraticCurveTo(144, cy + 12, 128, cy + 12.5);
  ctx.quadraticCurveTo(112, cy + 12, 101, cy);
  ctx.closePath();
  ctx.fill();

  // Inner K-beauty gradient tint (그라데이션 립)
  const innerGrad = ctx.createRadialGradient(128, cy + 1, 2, 128, cy + 2, 26);
  innerGrad.addColorStop(0, lp.inner);
  innerGrad.addColorStop(0.7, lp.outer);
  innerGrad.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = innerGrad;
  ctx.globalAlpha = 0.88;
  ctx.beginPath();
  ctx.ellipse(128, cy + 1.5, 22, 6.5, 0, 0, Math.PI * 2);
  ctx.fill();

  // Center mouth parting line with upturned Korean smile corners (입꼬리)
  ctx.globalAlpha = 0.85;
  ctx.strokeStyle = config.eyeStyle === 'fierce_dokkaebi' ? '#5E2A25' : '#8E3E3B';
  ctx.lineWidth = 2.1;
  ctx.lineCap = 'round';
  ctx.beginPath();
  if (config.eyeStyle === 'fierce_dokkaebi') {
    // Confident smirking Dokkaebi grin
    ctx.moveTo(98, cy - 2);
    ctx.quadraticCurveTo(128, cy + 6, 158, cy - 4);
  } else {
    ctx.moveTo(101, cy - 1);
    ctx.quadraticCurveTo(116, cy + 2.2, 128, cy + 0.8);
    ctx.quadraticCurveTo(140, cy + 2.2, 155, cy - 1);
  }
  ctx.stroke();

  // Glossy K-beauty lower lip catchlight
  if (lp.gloss) {
    ctx.fillStyle = 'rgba(255, 255, 255, 0.58)';
    ctx.beginPath();
    ctx.ellipse(123, cy + 6, 6.5, 1.9, 0, 0, Math.PI * 2);
    ctx.ellipse(135, cy + 5.8, 3.2, 1.5, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  // Chin soft shadow underneath lower lip
  ctx.fillStyle = pal.deepShadow;
  ctx.globalAlpha = 0.28;
  ctx.beginPath();
  ctx.ellipse(128, cy + 16, 11, 2.6, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawKoreanEyePair(
  ctx: any,
  config: KoreanFaceConfig,
  pal: SkinPalette,
  blink: boolean
): void {
  drawSingleKoreanEye(ctx, config, pal, 'left', blink);
  drawSingleKoreanEye(ctx, config, pal, 'right', blink);
}

function drawSingleKoreanEye(
  ctx: any,
  config: KoreanFaceConfig,
  pal: SkinPalette,
  side: 'left' | 'right',
  blink: boolean
): void {
  // Left eye on canvas is viewer-left (x ~ 76), Right eye is viewer-right (x ~ 180)
  // Inner corner (toward nose at x=128) vs Outer corner (toward temple)
  const isLeft = side === 'left';
  const cx = isLeft ? 76 : 180;
  const cy = 136;
  const innerX = isLeft ? 105 : 151;
  const outerX = isLeft ? 46 : 210;
  const dirOut = isLeft ? -1 : 1; // direction toward outer temple

  ctx.save();

  // Blinking or happy Korean Eye-Smile (눈웃음) when blinking
  if (blink || config.eyeStyle === 'eye_smile') {
    const isHappySmile = config.eyeStyle === 'eye_smile' && !blink;

    // Aegyo-sal warm puff below eye matched naturally to skin highlight
    ctx.strokeStyle = pal.highlight;
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 4.0;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(innerX - dirOut * 6, cy + 10);
    ctx.quadraticCurveTo(cx, cy + 15, outerX - dirOut * 6, cy + 9);
    ctx.stroke();

    ctx.strokeStyle = pal.deepShadow;
    ctx.globalAlpha = 0.24;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(innerX - dirOut * 8, cy + 14.5);
    ctx.quadraticCurveTo(cx, cy + 19, outerX - dirOut * 8, cy + 13.5);
    ctx.stroke();
    ctx.globalAlpha = 1;

    if (isHappySmile) {
      // Iconic Korean crescent eye-smile (눈웃음) with subtle dark iris peek!
      ctx.strokeStyle = '#1B1316';
      ctx.lineWidth = 4.6;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(innerX, cy + 4);
      ctx.quadraticCurveTo(cx, cy - 12, outerX, cy + 2);
      ctx.stroke();

      // Delicate outer lash flick
      ctx.lineWidth = 2.6;
      ctx.beginPath();
      ctx.moveTo(outerX, cy + 2);
      ctx.lineTo(outerX + dirOut * 6, cy + 4);
      ctx.stroke();

      // Soft double crease above eye-smile
      ctx.strokeStyle = pal.deepShadow;
      ctx.globalAlpha = 0.55;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.moveTo(innerX, cy - 1);
      ctx.quadraticCurveTo(cx, cy - 18, outerX + dirOut * 2, cy - 5);
      ctx.stroke();
    } else {
      // Natural closed blink line
      ctx.strokeStyle = '#1E1518';
      ctx.lineWidth = 3.8;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(innerX, cy + 3);
      ctx.quadraticCurveTo(cx, cy + 8, outerX, cy + 2);
      ctx.stroke();
    }

    ctx.restore();
    return;
  }

  // OPEN KOREAN EYE STYLES: monolid (무쌍), soft_double (속쌍), sharp_warrior, gentle_elder, fierce_dokkaebi
  const isWarrior = config.eyeStyle === 'sharp_warrior' || config.eyeStyle === 'fierce_dokkaebi';
  const isSoftDouble = config.eyeStyle === 'soft_double';
  const isElder = config.eyeStyle === 'gentle_elder';

  // Eye vertical aperture: sleek almond shape (not round cartoon circles!)
  const topPeakY = isWarrior ? cy - 10.5 : isSoftDouble ? cy - 13.5 : cy - 11.5;
  const bottomPeakY = isWarrior ? cy + 9.5 : cy + 11;
  const innerCornerY = cy + 3.5; // Gentle East Asian epicanthic downward inner point
  const outerCornerY = isWarrior ? cy - 3.5 : isElder ? cy + 2.5 : cy - 0.5;

  // Soft upper orbital socket warmth
  ctx.fillStyle = pal.midShadow;
  ctx.globalAlpha = 0.28;
  ctx.beginPath();
  ctx.ellipse(cx, cy - 6, 31, 14, 0, Math.PI, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;

  // 1. Sclera (almond silhouette) + clip for iris
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(innerX, innerCornerY);
  ctx.bezierCurveTo(
    cx - dirOut * 14,
    topPeakY,
    cx + dirOut * 16,
    topPeakY - (isWarrior ? 1.5 : 0),
    outerX,
    outerCornerY
  );
  ctx.bezierCurveTo(
    cx + dirOut * 14,
    bottomPeakY,
    cx - dirOut * 12,
    bottomPeakY,
    innerX,
    innerCornerY
  );
  ctx.closePath();

  // Sclera gradient (soft ivory white with subtle top lid shadow)
  const scleraGrad = ctx.createLinearGradient(cx, topPeakY, cx, bottomPeakY);
  scleraGrad.addColorStop(0, '#DFD8D6');
  scleraGrad.addColorStop(0.28, '#FCF9F7');
  scleraGrad.addColorStop(1, '#F5EFECE0');
  ctx.fillStyle = scleraGrad;
  ctx.fill();

  ctx.clip();

  // 2. Rich Dark Brown / Espresso Korean Iris (짙은 갈색 눈동자)
  const irisX = cx + (isLeft ? 1.5 : -1.5);
  const irisY = cy - 0.5;
  const irisR = isSoftDouble ? 13.2 : 12.4;

  const irisGrad = ctx.createRadialGradient(irisX, irisY + 4, 2, irisX, irisY, irisR);
  if (config.eyeStyle === 'fierce_dokkaebi') {
    irisGrad.addColorStop(0, '#9E4B24');
    irisGrad.addColorStop(0.65, '#3D1B12');
    irisGrad.addColorStop(1, '#160B09');
  } else {
    irisGrad.addColorStop(0, '#5B392B');
    irisGrad.addColorStop(0.55, '#2C1B17');
    irisGrad.addColorStop(1, '#120C0C');
  }
  ctx.fillStyle = irisGrad;
  ctx.beginPath();
  ctx.arc(irisX, irisY, irisR, 0, Math.PI * 2);
  ctx.fill();

  // Warm lower crescent glow inside dark brown iris
  ctx.strokeStyle = config.eyeStyle === 'fierce_dokkaebi' ? 'rgba(235, 145, 66, 0.55)' : 'rgba(138, 92, 68, 0.5)';
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.arc(irisX, irisY + 1, irisR - 4, 0.25, Math.PI - 0.25);
  ctx.stroke();

  // Deep espresso-black pupil
  ctx.fillStyle = '#090708';
  ctx.beginPath();
  ctx.arc(irisX, irisY - 0.5, 5.6, 0, Math.PI * 2);
  ctx.fill();

  // Crisp Korean dual catchlights (초롱초롱 눈빛)
  ctx.fillStyle = '#FFFFFF';
  ctx.beginPath();
  ctx.arc(irisX - 4.2, irisY - 4.2, 3.1, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = 'rgba(255, 255, 255, 0.82)';
  ctx.beginPath();
  ctx.arc(irisX + 4.4, irisY + 3.6, 1.6, 0, Math.PI * 2);
  ctx.fill();

  // Subtle top eyelid shadow across top of iris/sclera
  ctx.fillStyle = 'rgba(20, 12, 14, 0.22)';
  ctx.fillRect(cx - 36, topPeakY - 4, 72, 7.5);

  ctx.restore(); // End eye sclera clip

  // 3. Characteristic Korean Eyelid Crease:
  // - Monolid (무쌍): smooth clean upper lid fold whisper right at outer corner only
  // - Soft Double (속쌍 / 인아웃라인): thin delicate tapered crease starting near inner corner
  ctx.lineCap = 'round';
  if (isSoftDouble) {
    ctx.strokeStyle = pal.deepShadow;
    ctx.globalAlpha = 0.72;
    ctx.lineWidth = 1.9;
    ctx.beginPath();
    ctx.moveTo(innerX - dirOut * 3, innerCornerY - 3.5);
    ctx.bezierCurveTo(
      cx - dirOut * 12,
      topPeakY - 5.5,
      cx + dirOut * 16,
      topPeakY - 6.2,
      outerX + dirOut * 3,
      outerCornerY - 4.5
    );
    ctx.stroke();
    ctx.globalAlpha = 1;
  } else {
    // Monolid subtle natural skin fold line hugging close to lash line
    ctx.strokeStyle = pal.deepShadow;
    ctx.globalAlpha = 0.45;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(cx - dirOut * 6, topPeakY - 2.2);
    ctx.quadraticCurveTo(cx + dirOut * 14, topPeakY - 2.8, outerX + dirOut * 3, outerCornerY - 3);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // 4. Clean Upper Lash Line & Epicanthic Inner Taper + Subtle Outer Wing
  ctx.strokeStyle = '#181114';
  ctx.lineWidth = isSoftDouble ? 3.9 : 3.6;
  ctx.beginPath();
  ctx.moveTo(innerX + (isLeft ? 1.5 : -1.5), innerCornerY + 1.2);
  ctx.bezierCurveTo(
    cx - dirOut * 14,
    topPeakY,
    cx + dirOut * 16,
    topPeakY - (isWarrior ? 1.5 : 0),
    outerX,
    outerCornerY
  );
  // Subtle natural Korean outer eyeliner extension
  ctx.lineTo(outerX + dirOut * (isSoftDouble ? 6.5 : 4.5), outerCornerY + (isWarrior ? -1.5 : 1.5));
  ctx.stroke();

  // Soft lower outer lash shadow (삼각존 음영 — classic K-beauty subtle outer-lower triangle shading!)
  ctx.strokeStyle = pal.deepShadow;
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  ctx.moveTo(outerX + dirOut * 2, outerCornerY + 1);
  ctx.quadraticCurveTo(cx + dirOut * 14, bottomPeakY + 0.5, cx, bottomPeakY);
  ctx.stroke();
  ctx.globalAlpha = 1;

  // 5. Aegyo-sal (애교살) — soft natural puff + delicate crease line below eye!
  ctx.strokeStyle = pal.highlight;
  ctx.globalAlpha = 0.34;
  ctx.lineWidth = 3.6;
  ctx.beginPath();
  ctx.moveTo(innerX - dirOut * 7, bottomPeakY + 2.5);
  ctx.quadraticCurveTo(cx, bottomPeakY + 6.2, outerX - dirOut * 7, bottomPeakY + 1.5);
  ctx.stroke();

  ctx.strokeStyle = pal.deepShadow;
  ctx.globalAlpha = 0.24;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(innerX - dirOut * 9, bottomPeakY + 6.8);
  ctx.quadraticCurveTo(cx, bottomPeakY + 9.8, outerX - dirOut * 9, bottomPeakY + 5.8);
  ctx.stroke();
  ctx.globalAlpha = 1;

  // Gentle elder outer smile crinkles (눈가 미소 주름)
  if (isElder) {
    ctx.strokeStyle = pal.deepShadow;
    ctx.globalAlpha = 0.45;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.moveTo(outerX + dirOut * 4, outerCornerY + 1);
    ctx.lineTo(outerX + dirOut * 12, outerCornerY + 4);
    ctx.moveTo(outerX + dirOut * 3, outerCornerY + 6);
    ctx.lineTo(outerX + dirOut * 10, outerCornerY + 10);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  ctx.restore();
}

function drawKoreanBrows(ctx: any, config: KoreanFaceConfig): void {
  const browColor =
    config.browStyle === 'elder_silver'
      ? '#72757E'
      : shadeHex(config.hairColor, 18);

  for (const side of ['left', 'right'] as const) {
    const isLeft = side === 'left';
    const innerX = isLeft ? 105 : 151;
    const outerX = isLeft ? 44 : 212;
    const dirOut = isLeft ? -1 : 1;

    ctx.save();
    ctx.fillStyle = browColor;
    ctx.strokeStyle = browColor;
    ctx.lineCap = 'round';

    if (config.browStyle === 'straight_bold' || config.browStyle === 'warrior_slant') {
      const slant = config.browStyle === 'warrior_slant' ? -8 : -2.5;
      ctx.globalAlpha = 0.88;
      ctx.beginPath();
      ctx.moveTo(innerX, 108);
      ctx.quadraticCurveTo((innerX + outerX) / 2, 104 + slant * 0.5, outerX, 105 + slant);
      ctx.lineTo(outerX + dirOut * 3, 111 + slant);
      ctx.quadraticCurveTo((innerX + outerX) / 2, 112 + slant * 0.4, innerX, 115);
      ctx.closePath();
      ctx.fill();
    } else if (config.browStyle === 'arched_idol') {
      // Soft straight-arch K-idol brow
      ctx.globalAlpha = 0.82;
      ctx.lineWidth = 6.2;
      ctx.beginPath();
      ctx.moveTo(innerX, 108);
      ctx.quadraticCurveTo(innerX + dirOut * 36, 102, outerX, 108);
      ctx.stroke();
    } else {
      // Classic Korean straight natural eyebrow (일자 눈썹)
      ctx.globalAlpha = 0.8;
      ctx.lineWidth = config.browStyle === 'elder_silver' ? 6.5 : 6.0;
      ctx.beginPath();
      ctx.moveTo(innerX, 108);
      ctx.quadraticCurveTo((innerX + outerX) / 2, 105.5, outerX, 107.5);
      ctx.stroke();
    }

    // Soft inner brow feathering
    ctx.globalAlpha = 0.35;
    ctx.fillStyle = SKIN_PALETTES[config.skinTone].base;
    ctx.beginPath();
    ctx.arc(innerX + (isLeft ? 2 : -2), 109, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}

function drawFrontHair(ctx: any, config: KoreanFaceConfig): void {
  const baseHair = config.hairColor;
  const darkHair = shadeHex(baseHair, -22);
  const shineHair = shadeHex(baseHair, 38);

  ctx.save();

  switch (config.hairStyle) {
    case 'comma_twoblock': {
      // Modern Korean Two-Block Comma Hair (투블럭 가르마 콤마펌)
      ctx.fillStyle = baseHair;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(256, 0);
      ctx.lineTo(256, 76);
      // Right side curtain bang sweeping outward
      ctx.bezierCurveTo(234, 96, 198, 86, 162, 54);
      // 6:4 hair part at x ~ 152
      ctx.quadraticCurveTo(150, 44, 138, 54);
      // Iconic Left S-shaped Comma Curl sweeping inward over forehead!
      ctx.bezierCurveTo(114, 72, 104, 104, 122, 111);
      ctx.bezierCurveTo(92, 112, 74, 86, 62, 68);
      ctx.bezierCurveTo(42, 76, 18, 92, 0, 82);
      ctx.closePath();
      ctx.fill();

      // Glossy K-pop hair shine band
      ctx.strokeStyle = shineHair;
      ctx.globalAlpha = 0.55;
      ctx.lineWidth = 5;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(32, 34);
      ctx.quadraticCurveTo(88, 26, 134, 38);
      ctx.moveTo(164, 36);
      ctx.quadraticCurveTo(205, 28, 236, 44);
      ctx.stroke();
      ctx.globalAlpha = 1;

      // Tapered side framing wisps
      ctx.fillStyle = baseHair;
      ctx.beginPath();
      ctx.moveTo(0, 62);
      ctx.lineTo(15, 68);
      ctx.quadraticCurveTo(8, 102, 2, 126);
      ctx.lineTo(0, 126);
      ctx.closePath();
      ctx.fill();

      ctx.beginPath();
      ctx.moveTo(256, 62);
      ctx.lineTo(241, 68);
      ctx.quadraticCurveTo(248, 102, 254, 126);
      ctx.lineTo(256, 126);
      ctx.closePath();
      ctx.fill();
      break;
    }

    case 'seethrough_long': {
      // Korean See-Through Bangs (시스루뱅) + Face-framing side locks (애교머리)
      ctx.fillStyle = baseHair;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(256, 0);
      ctx.lineTo(256, 256);
      ctx.lineTo(235, 256);
      ctx.quadraticCurveTo(232, 124, 212, 68);
      ctx.quadraticCurveTo(176, 48, 128, 46);
      ctx.quadraticCurveTo(80, 48, 44, 68);
      ctx.quadraticCurveTo(24, 124, 21, 256);
      ctx.lineTo(0, 256);
      ctx.closePath();
      ctx.fill();

      // Delicate feathery curved Korean see-through wisps across forehead!
      const wisps: Array<[number, number, number]> = [
        [62, 96, -8],
        [82, 101, -5],
        [104, 104, -3],
        [124, 103, 1],
        [144, 104, 3],
        [168, 101, 5],
        [190, 96, 8],
      ];
      for (let i = 0; i < wisps.length; i++) {
        const [sx, endY, sweep] = wisps[i];
        ctx.strokeStyle = i % 2 === 0 ? baseHair : darkHair;
        ctx.lineWidth = i === 2 || i === 4 ? 5.2 : 4.2;
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(sx, 42);
        ctx.quadraticCurveTo(sx + sweep * 0.4, 72, sx + sweep, endY);
        ctx.stroke();
      }

      // Glossy crown angel-ring highlight (엔젤링)
      ctx.strokeStyle = shineHair;
      ctx.globalAlpha = 0.5;
      ctx.lineWidth = 6;
      ctx.beginPath();
      ctx.moveTo(28, 26);
      ctx.quadraticCurveTo(128, 18, 228, 26);
      ctx.stroke();
      ctx.globalAlpha = 1;
      break;
    }

    case 'joseon_gat': {
      // Swept-up hair hairline + Traditional Joseon Black Horsehair Manggeon (망건) headband
      ctx.fillStyle = baseHair;
      ctx.fillRect(0, 0, 256, 46);

      // Woven black horsehair Manggeon band across forehead
      ctx.fillStyle = 'rgba(20, 20, 26, 0.9)';
      ctx.fillRect(0, 42, 256, 28);

      // Subtle woven mesh texture on Manggeon
      ctx.strokeStyle = 'rgba(75, 78, 92, 0.45)';
      ctx.lineWidth = 1.2;
      for (let x = 0; x < 256; x += 8) {
        ctx.beginPath();
        ctx.moveTo(x, 42);
        ctx.lineTo(x + 6, 70);
        ctx.stroke();
      }
      // Gold trim border on Manggeon
      ctx.fillStyle = '#C9A24B';
      ctx.fillRect(0, 41, 256, 2.5);
      ctx.fillRect(0, 69, 256, 2.5);

      // Beaded Gat chin-strap (갓끈) framing outer jawline
      ctx.fillStyle = '#2B2220';
      for (let y = 148; y < 248; y += 11) {
        ctx.beginPath();
        ctx.arc(8, y, 3.5, 0, Math.PI * 2);
        ctx.arc(248, y, 3.5, 0, Math.PI * 2);
        ctx.fill();
      }
      break;
    }

    case 'idol_layered': {
      // K-Idol Curtain Bangs + Pearl Hairpins (아이돌 레이어드 앞머리 + 헤어핀)
      ctx.fillStyle = baseHair;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(256, 0);
      ctx.lineTo(256, 256);
      ctx.lineTo(234, 256);
      ctx.quadraticCurveTo(232, 130, 206, 86);
      ctx.quadraticCurveTo(168, 62, 128, 46);
      ctx.quadraticCurveTo(88, 62, 50, 86);
      ctx.quadraticCurveTo(24, 130, 22, 256);
      ctx.lineTo(0, 256);
      ctx.closePath();
      ctx.fill();

      // Delicate center wisps
      ctx.fillStyle = darkHair;
      for (const sx of [98, 118, 138, 158]) {
        ctx.beginPath();
        ctx.moveTo(sx - 5, 44);
        ctx.quadraticCurveTo(sx, 76, sx + (sx < 128 ? -4 : 4), 95);
        ctx.quadraticCurveTo(sx + 4, 72, sx + 5, 44);
        ctx.fill();
      }

      // Cute K-idol pastel pearl hair clips on viewer-right side!
      ctx.strokeStyle = '#FFE8A3';
      ctx.lineWidth = 3.5;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(208, 72);
      ctx.lineTo(236, 65);
      ctx.stroke();
      ctx.strokeStyle = '#FFB8D0';
      ctx.beginPath();
      ctx.moveTo(212, 82);
      ctx.lineTo(239, 76);
      ctx.stroke();

      // Crown shine
      ctx.strokeStyle = shineHair;
      ctx.globalAlpha = 0.52;
      ctx.lineWidth = 5.5;
      ctx.beginPath();
      ctx.moveTo(36, 28);
      ctx.quadraticCurveTo(128, 18, 220, 28);
      ctx.stroke();
      ctx.globalAlpha = 1;
      break;
    }

    case 'halmeoni_perm': {
      // Classic Korean Grandma Curly Perm (할머니 파마)
      ctx.fillStyle = darkHair;
      ctx.fillRect(0, 0, 256, 56);
      const puffs = [
        [20, 56, 28],
        [52, 48, 28],
        [88, 44, 29],
        [128, 42, 30],
        [168, 44, 29],
        [204, 48, 28],
        [236, 56, 28],
        [10, 92, 22],
        [246, 92, 22],
      ];
      for (const [px, py, pr] of puffs) {
        ctx.fillStyle = baseHair;
        ctx.beginPath();
        ctx.arc(px, py, pr, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = shineHair;
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.arc(px - 3, py - 4, pr * 0.55, Math.PI * 0.9, Math.PI * 1.85);
        ctx.stroke();
      }
      break;
    }

    case 'binyeo_bun': {
      // Traditional Center-Parted Sleek Korean Hair (가르마 쪽진머리)
      ctx.fillStyle = baseHair;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(256, 0);
      ctx.lineTo(256, 108);
      ctx.quadraticCurveTo(212, 72, 131, 42);
      ctx.lineTo(125, 42);
      ctx.quadraticCurveTo(44, 72, 0, 108);
      ctx.closePath();
      ctx.fill();

      // Crisp center hair part (가르마)
      ctx.fillStyle = SKIN_PALETTES[config.skinTone].highlight;
      ctx.fillRect(126, 0, 4, 44);

      // Sleek silk hair shine
      ctx.strokeStyle = shineHair;
      ctx.globalAlpha = 0.5;
      ctx.lineWidth = 5;
      ctx.beginPath();
      ctx.moveTo(26, 48);
      ctx.quadraticCurveTo(75, 28, 118, 28);
      ctx.moveTo(138, 28);
      ctx.quadraticCurveTo(181, 28, 230, 48);
      ctx.stroke();
      ctx.globalAlpha = 1;
      break;
    }

    case 'student_cut': {
      // Soft Korean Dandy Cut (댄디컷)
      ctx.fillStyle = baseHair;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(256, 0);
      ctx.lineTo(256, 86);
      ctx.lineTo(238, 96);
      ctx.lineTo(222, 82);
      ctx.lineTo(196, 98);
      ctx.lineTo(168, 86);
      ctx.lineTo(142, 100);
      ctx.lineTo(112, 92);
      ctx.lineTo(84, 100);
      ctx.lineTo(54, 86);
      ctx.lineTo(26, 96);
      ctx.lineTo(0, 84);
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = shineHair;
      ctx.globalAlpha = 0.48;
      ctx.lineWidth = 5;
      ctx.beginPath();
      ctx.moveTo(34, 36);
      ctx.quadraticCurveTo(128, 24, 222, 36);
      ctx.stroke();
      ctx.globalAlpha = 1;
      break;
    }

    case 'satgat_farmer': {
      // Traditional linen headband (두건) under bamboo Satgat hat
      ctx.fillStyle = baseHair;
      ctx.fillRect(0, 0, 256, 52);
      ctx.fillStyle = '#EFE8D8';
      ctx.fillRect(0, 36, 256, 32);
      ctx.fillStyle = '#D5CCB8';
      ctx.fillRect(0, 64, 256, 5);
      break;
    }

    case 'dokkaebi_horn': {
      // Wild Korean folklore warrior hair + crimson/gold headband
      ctx.fillStyle = baseHair;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(256, 0);
      ctx.lineTo(256, 92);
      ctx.lineTo(224, 68);
      ctx.lineTo(192, 86);
      ctx.lineTo(128, 62);
      ctx.lineTo(64, 86);
      ctx.lineTo(32, 68);
      ctx.lineTo(0, 92);
      ctx.closePath();
      ctx.fill();

      ctx.fillStyle = '#9E2328';
      ctx.fillRect(0, 48, 256, 24);
      ctx.fillStyle = '#E6B84C';
      ctx.fillRect(0, 47, 256, 3);
      ctx.fillRect(0, 70, 256, 3);
      break;
    }
  }

  ctx.restore();
}

function drawFrontGlassesOverlay(ctx: any, glasses: KoreanFaceConfig['glasses']): void {
  ctx.save();
  const isTinted = glasses === 'tinted_idol';
  ctx.strokeStyle = isTinted ? '#D4AF37' : '#2D3038';
  ctx.lineWidth = 4.2;

  for (const cx of [76, 180]) {
    if (isTinted) {
      ctx.fillStyle = 'rgba(255, 162, 185, 0.24)';
      ctx.beginPath();
      ctx.arc(cx, 136, 34, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.fillStyle = 'rgba(210, 238, 255, 0.14)';
      ctx.beginPath();
      ctx.arc(cx, 136, 34, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.beginPath();
    ctx.arc(cx, 136, 34, 0, Math.PI * 2);
    ctx.stroke();

    // Subtle glass reflection diagonal
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.45)';
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.moveTo(cx - 18, 118);
    ctx.lineTo(cx - 6, 108);
    ctx.stroke();
    ctx.strokeStyle = isTinted ? '#D4AF37' : '#2D3038';
    ctx.lineWidth = 4.2;
  }

  // Nose bridge bar & side temples
  ctx.beginPath();
  ctx.moveTo(110, 134);
  ctx.quadraticCurveTo(128, 128, 146, 134);
  ctx.moveTo(0, 132);
  ctx.lineTo(42, 134);
  ctx.moveTo(214, 134);
  ctx.lineTo(256, 132);
  ctx.stroke();

  ctx.restore();
}

function drawHeadSide(
  config: KoreanFaceConfig,
  side: 'left' | 'right',
  createCanvas: CanvasFactory
): CanvasLike {
  const S = 256;
  const canvas = createCanvas(S, S);
  const ctx = canvas.getContext('2d');
  const pal = SKIN_PALETTES[config.skinTone];
  const baseHair = config.hairColor;
  const darkHair = shadeHex(baseHair, -20);

  // Skin base
  ctx.fillStyle = pal.base;
  ctx.fillRect(0, 0, S, S);

  // Which horizontal side faces the front of the head?
  // In Three.js BoxGeometry:
  // +x (right of cube, character's left cheek): u=0 is +z (front), u=1 is -z (back)
  // -x (left of cube, character's right cheek): u=0 is -z (back), u=1 is +z (front)
  const frontOnLeft = side === 'right';

  // Hair coverage on top & back of side profile
  ctx.fillStyle = baseHair;
  ctx.fillRect(0, 0, S, 76);

  const backStart = frontOnLeft ? 112 : 0;
  const backWidth = 144;

  if (config.hairStyle === 'seethrough_long' || config.hairStyle === 'idol_layered') {
    // Full flowing long side hair leaving ear peek
    ctx.fillStyle = baseHair;
    ctx.fillRect(backStart, 48, backWidth, S - 48);
    ctx.fillStyle = darkHair;
    for (let x = backStart + 18; x < backStart + backWidth; x += 26) {
      ctx.fillRect(x, 60, 4, S - 60);
    }
  } else if (config.hairStyle === 'halmeoni_perm') {
    ctx.fillStyle = baseHair;
    ctx.fillRect(backStart, 48, backWidth, 148);
    for (let y = 60; y < 185; y += 34) {
      ctx.beginPath();
      ctx.arc(frontOnLeft ? 118 : 138, y, 24, 0, Math.PI * 2);
      ctx.fill();
    }
  } else {
    // Korean Two-Block undercut / neat tapered back & sideburn!
    ctx.fillStyle = baseHair;
    ctx.fillRect(backStart, 48, backWidth, 128);
    // Undercut soft fade below y=176
    ctx.fillStyle = darkHair;
    ctx.globalAlpha = 0.45;
    ctx.fillRect(backStart + (frontOnLeft ? 28 : 0), 176, backWidth - 28, 42);
    ctx.globalAlpha = 1;

    // Neat Korean sideburn (구레나룻) in front of ear
    const sbX = frontOnLeft ? 78 : 162;
    ctx.fillStyle = baseHair;
    ctx.fillRect(sbX, 72, 16, 74);
  }

  // Headbands wrap around sides!
  if (config.hairStyle === 'joseon_gat') {
    ctx.fillStyle = 'rgba(20, 20, 26, 0.9)';
    ctx.fillRect(0, 42, S, 28);
    ctx.fillStyle = '#C9A24B';
    ctx.fillRect(0, 41, S, 2.5);
    ctx.fillRect(0, 69, S, 2.5);
    // Traditional jade Gwanja (관자) ring on temple!
    ctx.strokeStyle = '#7FD1AE';
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(128, 56, 8, 0, Math.PI * 2);
    ctx.stroke();
  } else if (config.hairStyle === 'satgat_farmer') {
    ctx.fillStyle = '#EFE8D8';
    ctx.fillRect(0, 36, S, 32);
  } else if (config.hairStyle === 'dokkaebi_horn') {
    ctx.fillStyle = '#9E2328';
    ctx.fillRect(0, 48, S, 24);
  }

  // Sculpted Ear at center of side head
  const earX = frontOnLeft ? 108 : 148;
  ctx.fillStyle = pal.midShadow;
  ctx.beginPath();
  ctx.ellipse(earX, 145, 16, 26, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = pal.base;
  ctx.beginPath();
  ctx.ellipse(earX, 145, 13, 22, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = pal.earInner;
  ctx.beginPath();
  ctx.ellipse(earX, 146, 6, 12, 0, 0, Math.PI * 2);
  ctx.fill();

  // Glasses temple arm on side
  if (config.glasses !== 'none') {
    ctx.strokeStyle = config.glasses === 'tinted_idol' ? '#D4AF37' : '#2D3038';
    ctx.lineWidth = 4.5;
    ctx.beginPath();
    if (frontOnLeft) {
      ctx.moveTo(0, 132);
      ctx.lineTo(earX + 6, 130);
    } else {
      ctx.moveTo(S, 132);
      ctx.lineTo(earX - 6, 130);
    }
    ctx.stroke();
  }

  return canvas;
}

function drawHeadBack(config: KoreanFaceConfig, createCanvas: CanvasFactory): CanvasLike {
  const S = 256;
  const canvas = createCanvas(S, S);
  const ctx = canvas.getContext('2d');
  const pal = SKIN_PALETTES[config.skinTone];
  const baseHair = config.hairColor;
  const darkHair = shadeHex(baseHair, -22);
  const shineHair = shadeHex(baseHair, 34);

  ctx.fillStyle = pal.base;
  ctx.fillRect(0, 0, S, S);

  if (config.hairStyle === 'seethrough_long' || config.hairStyle === 'idol_layered') {
    ctx.fillStyle = baseHair;
    ctx.fillRect(0, 0, S, S);
    // Vertical silky hair texture strands
    ctx.fillStyle = darkHair;
    for (let x = 16; x < S; x += 24) {
      ctx.fillRect(x, 0, 5, S);
    }
    ctx.fillStyle = shineHair;
    ctx.globalAlpha = 0.35;
    ctx.fillRect(24, 48, S - 48, 18);
    ctx.globalAlpha = 1;

    // Traditional Korean Red & Gold Daenggi Ribbon (댕기) on seethrough_long!
    if (config.hairStyle === 'seethrough_long') {
      ctx.fillStyle = '#C92A3E';
      ctx.fillRect(108, 120, 40, 136);
      // Gold Korean floral embroidery on Daenggi
      ctx.strokeStyle = '#F2C94C';
      ctx.lineWidth = 3;
      ctx.strokeRect(113, 126, 30, 124);
      ctx.fillStyle = '#F2C94C';
      ctx.beginPath();
      ctx.arc(128, 165, 7, 0, Math.PI * 2);
      ctx.arc(128, 205, 7, 0, Math.PI * 2);
      ctx.fill();
    }
  } else if (config.hairStyle === 'binyeo_bun') {
    ctx.fillStyle = baseHair;
    ctx.fillRect(0, 0, S, 215);
    // Low nape hair bun shadow (3D bun also attached!)
    ctx.fillStyle = darkHair;
    ctx.beginPath();
    ctx.arc(128, 176, 46, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#C92A3E';
    ctx.lineWidth = 6;
    ctx.beginPath();
    ctx.arc(128, 176, 32, 0, Math.PI * 2);
    ctx.stroke();
  } else if (config.hairStyle === 'halmeoni_perm') {
    ctx.fillStyle = darkHair;
    ctx.fillRect(0, 0, S, 210);
    for (let y = 28; y <= 196; y += 38) {
      for (let x = 24; x <= 232; x += 42) {
        ctx.fillStyle = baseHair;
        ctx.beginPath();
        ctx.arc(x, y, 25, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  } else {
    // Neat Korean Two-Block / tapered neckline!
    ctx.fillStyle = baseHair;
    ctx.fillRect(0, 0, S, 182);
    ctx.fillStyle = darkHair;
    ctx.globalAlpha = 0.55;
    ctx.fillRect(22, 182, S - 44, 42);
    ctx.globalAlpha = 1;
  }

  return canvas;
}

function drawHeadTop(config: KoreanFaceConfig, createCanvas: CanvasFactory): CanvasLike {
  const S = 256;
  const canvas = createCanvas(S, S);
  const ctx = canvas.getContext('2d');
  const baseHair = config.hairColor;
  const shineHair = shadeHex(baseHair, 30);

  ctx.fillStyle = baseHair;
  ctx.fillRect(0, 0, S, S);

  // Subtle crown whorl / part
  ctx.strokeStyle = shineHair;
  ctx.globalAlpha = 0.4;
  ctx.lineWidth = 8;
  ctx.beginPath();
  ctx.arc(128, 128, 56, 0, Math.PI * 2);
  ctx.stroke();
  ctx.globalAlpha = 1;

  if (config.hairStyle === 'binyeo_bun') {
    ctx.fillStyle = SKIN_PALETTES[config.skinTone].highlight;
    ctx.fillRect(125, 110, 6, 146);
  }

  return canvas;
}

function drawHeadBottom(config: KoreanFaceConfig, createCanvas: CanvasFactory): CanvasLike {
  const S = 128;
  const canvas = createCanvas(S, S);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = SKIN_PALETTES[config.skinTone].deepShadow;
  ctx.fillRect(0, 0, S, S);
  return canvas;
}

interface OutfitColors {
  topPrimary: string;
  topSecondary: string;
  collar: string;
  accent: string;
  legColor: string;
  shoeColor: string;
  isHanbok?: boolean;
  isGuard?: boolean;
  isFloralVest?: boolean;
}

const OUTFIT_PALETTES: Record<OutfitStyleId, OutfitColors> = {
  seoul_street: {
    topPrimary: '#DDE6F7',
    topSecondary: '#39558F',
    collar: '#FFFFFF',
    accent: '#FF7C9C',
    legColor: '#2A3347',
    shoeColor: '#F5F7FA',
  },
  hanbok_pink: {
    topPrimary: '#FFF5F7', // White/blush Jeogori
    topSecondary: '#F26B8A', // Rose Chima skirt high waist!
    collar: '#FFFFFF',
    accent: '#C92A49', // Goreum ribbon
    legColor: '#E35677',
    shoeColor: '#FFF5F7',
    isHanbok: true,
  },
  hanbok_royal: {
    topPrimary: '#DCE9FA', // Sky-blue Jeogori
    topSecondary: '#4B3B78', // Royal plum-indigo Chima
    collar: '#FFFFFF',
    accent: '#E8B94F', // Gold royal trim
    legColor: '#3E3066',
    shoeColor: '#DCE9FA',
    isHanbok: true,
  },
  joseon_guard: {
    topPrimary: '#1E3156', // Joseon navy robe
    topSecondary: '#9E2432', // Crimson sash & trim
    collar: '#ECEAE4',
    accent: '#E3B94B', // Gold royal medallion (흉배)
    legColor: '#192642',
    shoeColor: '#18181E',
    isGuard: true,
  },
  halmeoni_vest: {
    topPrimary: '#934A6E', // Cozy plum knit
    topSecondary: '#F6EFE6', // Quilted floral vest
    collar: '#EADAC8',
    accent: '#E56B81',
    legColor: '#4A424F',
    shoeColor: '#3A2E2B',
    isFloralVest: true,
  },
  carpenter_hemp: {
    topPrimary: '#D9CBB5', // Traditional hemp 생활한복
    topSecondary: '#8C7254',
    collar: '#F5EFE4',
    accent: '#5C4833',
    legColor: '#7A644B',
    shoeColor: '#4A3B2A',
  },
  student_hoodie: {
    topPrimary: '#3B6E8C', // Seoul university hoodie
    topSecondary: '#294E66',
    collar: '#F2F5F8',
    accent: '#FFD166',
    legColor: '#2C313D',
    shoeColor: '#FFFFFF',
  },
  hanbok_apron: {
    topPrimary: '#FCE4C8', // Apricot Jeogori
    topSecondary: '#4A7C6F', // Jade green skirt + apron
    collar: '#FFFFFF',
    accent: '#D95D4E',
    legColor: '#3D695D',
    shoeColor: '#FCE4C8',
    isHanbok: true,
  },
  farmer_linen: {
    topPrimary: '#EDE5D2',
    topSecondary: '#5F8758',
    collar: '#FFFFFF',
    accent: '#A67B51',
    legColor: '#56694F',
    shoeColor: '#594431',
  },
  dokkaebi_armor: {
    topPrimary: '#5E2428',
    topSecondary: '#D98A2B', // Tiger-stripe gold-amber
    collar: '#291518',
    accent: '#F2C94C',
    legColor: '#2E1E24',
    shoeColor: '#1A1215',
  },
};

function drawTorso(
  outfit: OutfitStyleId,
  skinTone: SkinToneId,
  face: 'front' | 'back' | 'side',
  createCanvas: CanvasFactory
): CanvasLike {
  const W = 128;
  const H = 192;
  const canvas = createCanvas(W, H);
  const ctx = canvas.getContext('2d');
  const op = OUTFIT_PALETTES[outfit];
  const skin = SKIN_PALETTES[skinTone];

  ctx.fillStyle = op.topPrimary;
  ctx.fillRect(0, 0, W, H);

  if (op.isHanbok) {
    // Short Jeogori top (y: 0..76) + High-waisted Korean Chima skirt (y: 76..192)
    ctx.fillStyle = op.topSecondary;
    ctx.fillRect(0, 74, W, H - 74);

    // Pleated vertical folds on Hanbok Chima
    ctx.strokeStyle = shadeHex(op.topSecondary, -24);
    ctx.lineWidth = 3;
    for (let x = 14; x < W; x += 18) {
      ctx.beginPath();
      ctx.moveTo(x, 76);
      ctx.lineTo(x, H);
      ctx.stroke();
    }

    // Gold royal pattern band on hem
    ctx.fillStyle = op.accent;
    ctx.fillRect(0, 70, W, 6);

    if (face === 'front') {
      // V-neck skin & crisp white Korean Dongjeong (동정) collar!
      ctx.fillStyle = skin.base;
      ctx.beginPath();
      ctx.moveTo(42, 0);
      ctx.lineTo(86, 0);
      ctx.lineTo(64, 34);
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = op.collar;
      ctx.lineWidth = 10;
      ctx.beginPath();
      ctx.moveTo(38, 0);
      ctx.lineTo(68, 42);
      ctx.moveTo(90, 0);
      ctx.lineTo(54, 48);
      ctx.stroke();

      // Iconic flowing Hanbok Goreum (고름) ribbon bow on chest!
      ctx.fillStyle = op.accent;
      ctx.beginPath();
      ctx.ellipse(72, 50, 14, 7, 0.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillRect(62, 52, 10, 88);
      ctx.fillRect(75, 52, 9, 74);
    }
  } else if (op.isGuard) {
    // Joseon Royal Guard Armor / Robe (구군복)
    ctx.fillStyle = op.topSecondary;
    ctx.fillRect(0, 96, W, 22); // Crimson waist sash
    ctx.fillStyle = op.accent;
    ctx.fillRect(46, 98, 36, 18); // Gold belt buckle

    if (face === 'front') {
      // White inner Joseon collar
      ctx.strokeStyle = op.collar;
      ctx.lineWidth = 9;
      ctx.beginPath();
      ctx.moveTo(40, 0);
      ctx.lineTo(74, 48);
      ctx.moveTo(88, 0);
      ctx.lineTo(58, 42);
      ctx.stroke();

      // Gold Joseon Royal Chest Medallion (흉배 / 補)
      ctx.fillStyle = '#2B1F14';
      ctx.beginPath();
      ctx.arc(64, 62, 22, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = op.accent;
      ctx.lineWidth = 3.5;
      ctx.stroke();
      ctx.fillStyle = op.accent;
      ctx.beginPath();
      ctx.arc(64, 62, 11, 0, Math.PI * 2);
      ctx.fill();
    }
  } else if (op.isFloralVest) {
    // Halmeoni Quilted Floral Vest (꽃무늬 조끼)!
    ctx.fillStyle = op.topSecondary;
    ctx.fillRect(0, 12, W, H - 12);
    if (face === 'front') {
      ctx.fillStyle = op.topPrimary;
      ctx.fillRect(46, 0, 36, H);
    }
    // Cute little Korean market vest flowers
    for (let y = 28; y < H - 18; y += 32) {
      for (let x = 18; x < W - 12; x += 30) {
        if (face === 'front' && x > 42 && x < 86) continue;
        ctx.fillStyle = '#E55B78';
        ctx.beginPath();
        ctx.arc(x, y, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#FFD166';
        ctx.beginPath();
        ctx.arc(x, y, 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  } else if (outfit === 'dokkaebi_armor') {
    // Tiger-stripe waist sash & Korean Dokkaebi emblem
    ctx.fillStyle = op.topSecondary;
    ctx.fillRect(0, 108, W, 36);
    ctx.fillStyle = '#1E1412';
    for (let x = 8; x < W; x += 22) {
      ctx.beginPath();
      ctx.moveTo(x, 108);
      ctx.lineTo(x + 10, 108);
      ctx.lineTo(x + 4, 136);
      ctx.closePath();
      ctx.fill();
    }
    if (face === 'front') {
      ctx.strokeStyle = op.accent;
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.arc(64, 58, 20, 0, Math.PI * 2);
      ctx.stroke();
    }
  } else {
    // Modern Seoul Jacket / Hoodie / Hemp Tunic
    if (face === 'front') {
      ctx.fillStyle = skin.base;
      ctx.beginPath();
      ctx.arc(64, 6, 18, 0, Math.PI);
      ctx.fill();

      ctx.fillStyle = op.topSecondary;
      ctx.fillRect(0, 0, 32, H);
      ctx.fillRect(W - 32, 0, 32, H);

      // Hoodie strings or varsity stripes
      ctx.strokeStyle = op.collar;
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.moveTo(52, 18);
      ctx.lineTo(52, 66);
      ctx.moveTo(76, 18);
      ctx.lineTo(76, 66);
      ctx.stroke();

      // Pocket / badge accent
      ctx.fillStyle = op.accent;
      ctx.fillRect(88, 52, 20, 12);
    } else {
      ctx.fillStyle = op.topSecondary;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = op.accent;
      ctx.fillRect(24, 54, W - 48, 12);
    }
  }

  return canvas;
}

function drawArm(
  outfit: OutfitStyleId,
  skinTone: SkinToneId,
  createCanvas: CanvasFactory
): CanvasLike {
  const W = 64;
  const H = 192;
  const canvas = createCanvas(W, H);
  const ctx = canvas.getContext('2d');
  const op = OUTFIT_PALETTES[outfit];
  const skin = SKIN_PALETTES[skinTone];

  // Sleeve top 75%, hand bottom 25%
  ctx.fillStyle = op.isHanbok ? op.topPrimary : op.topSecondary;
  ctx.fillRect(0, 0, W, 144);

  if (op.isHanbok) {
    // Colorful Saekdong / cuff band on Hanbok sleeve!
    ctx.fillStyle = op.accent;
    ctx.fillRect(0, 126, W, 18);
    ctx.fillStyle = op.collar;
    ctx.fillRect(0, 138, W, 6);
  } else {
    ctx.fillStyle = op.collar;
    ctx.fillRect(0, 136, W, 8);
  }

  // Korean character hand
  ctx.fillStyle = skin.base;
  ctx.fillRect(0, 144, W, 48);
  ctx.fillStyle = skin.midShadow;
  ctx.fillRect(0, 184, W, 8);

  return canvas;
}

function drawLeg(
  outfit: OutfitStyleId,
  _skinTone: SkinToneId,
  createCanvas: CanvasFactory
): CanvasLike {
  const W = 64;
  const H = 192;
  const canvas = createCanvas(W, H);
  const ctx = canvas.getContext('2d');
  const op = OUTFIT_PALETTES[outfit];

  ctx.fillStyle = op.legColor;
  ctx.fillRect(0, 0, W, 158);

  if (op.isHanbok) {
    // Vertical skirt pleats continuation
    ctx.fillStyle = shadeHex(op.legColor, -20);
    ctx.fillRect(14, 0, 5, 154);
    ctx.fillRect(42, 0, 5, 154);
  }

  // Shoes (Korean Gomusin / Hwa boots / White Seoul sneakers!)
  ctx.fillStyle = op.shoeColor;
  ctx.fillRect(0, 158, W, 34);
  ctx.fillStyle = shadeHex(op.shoeColor, -35);
  ctx.fillRect(0, 184, W, 8);

  return canvas;
}

export function renderCharacterPortraitDataUrl(
  config: KoreanFaceConfig,
  createCanvas: CanvasFactory = defaultBrowserFactory
): string {
  const S = 160;
  const canvas = createCanvas(S, S);
  const ctx = canvas.getContext('2d');

  // Soft Korean traditional circle backdrop
  const bg = ctx.createLinearGradient(0, 0, S, S);
  bg.addColorStop(0, '#1D2940');
  bg.addColorStop(1, '#312442');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, S, S);

  // Decorative warm moon glow behind head
  ctx.fillStyle = 'rgba(255, 214, 170, 0.16)';
  ctx.beginPath();
  ctx.arc(80, 74, 58, 0, Math.PI * 2);
  ctx.fill();

  const headCanvas = drawHeadFront(config, false, createCanvas);
  const torsoCanvas = drawTorso(config.outfitStyle, config.skinTone, 'front', createCanvas);

  // Shoulders
  ctx.drawImage(torsoCanvas, 34, 120, 92, 56);

  // Hat silhouette in 2D portrait if Gat or Satgat or Dokkaebi!
  if (config.hairStyle === 'joseon_gat') {
    ctx.fillStyle = 'rgba(18, 18, 24, 0.88)';
    ctx.fillRect(54, 4, 52, 28);
    ctx.beginPath();
    ctx.ellipse(80, 32, 74, 11, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#C9A24B';
    ctx.lineWidth = 1.8;
    ctx.stroke();
  } else if (config.hairStyle === 'satgat_farmer') {
    ctx.fillStyle = '#D8BE88';
    ctx.beginPath();
    ctx.moveTo(80, 4);
    ctx.lineTo(148, 38);
    ctx.lineTo(12, 38);
    ctx.closePath();
    ctx.fill();
  } else if (config.hairStyle === 'dokkaebi_horn') {
    ctx.fillStyle = '#F2C94C';
    ctx.beginPath();
    ctx.moveTo(52, 26);
    ctx.lineTo(44, 4);
    ctx.lineTo(64, 24);
    ctx.moveTo(108, 26);
    ctx.lineTo(116, 4);
    ctx.lineTo(96, 24);
    ctx.fill();
  }

  // Head
  ctx.drawImage(headCanvas, 32, 26, 96, 96);

  // Binyeo jade pin sticking out on portrait
  if (config.hairStyle === 'binyeo_bun') {
    ctx.strokeStyle = '#68C7A6';
    ctx.lineWidth = 5;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(20, 96);
    ctx.lineTo(32, 96);
    ctx.moveTo(128, 96);
    ctx.lineTo(140, 96);
    ctx.stroke();
    ctx.fillStyle = '#E55B78';
    ctx.beginPath();
    ctx.arc(141, 96, 4.5, 0, Math.PI * 2);
    ctx.fill();
  }

  return canvas.toDataURL('image/png');
}
