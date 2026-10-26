import * as THREE from 'three';
import {
  KoreanFaceConfig,
  InventoryItemId,
} from '../types/game';
import { generateKoreanCharacterCanvases } from './KoreanSkinGenerator';

export interface CharacterRig {
  root: THREE.Group;
  bodyGroup: THREE.Group;
  headPivot: THREE.Group;
  headMesh: THREE.Mesh;
  leftArmPivot: THREE.Group;
  rightArmPivot: THREE.Group;
  leftLegPivot: THREE.Group;
  rightLegPivot: THREE.Group;
  rightHandMount: THREE.Group;
  frontFaceTex: THREE.CanvasTexture;
  blinkFaceTex: THREE.CanvasTexture;
  headMaterials: THREE.MeshLambertMaterial[];
  nameSprite?: THREE.Sprite;
  speechSprite?: THREE.Sprite;
  setBlinking: (blinking: boolean) => void;
  updateFaceConfig: (newConfig: KoreanFaceConfig) => void;
  animateWalk: (speed: number, time: number, swingProgress?: number) => void;
  dispose: () => void;
}

function makeTex(canvas: HTMLCanvasElement): THREE.CanvasTexture {
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.needsUpdate = true;
  return tex;
}

export function buildKoreanCharacterRig(
  initialConfig: KoreanFaceConfig,
  options?: {
    nameFa?: string;
    nameKo?: string;
    roleFa?: string;
    isHostile?: boolean;
  }
): CharacterRig {
  const root = new THREE.Group();
  const bodyGroup = new THREE.Group();
  root.add(bodyGroup);

  const headPivot = new THREE.Group();
  headPivot.position.set(0, 1.36, 0);
  bodyGroup.add(headPivot);

  const headGeo = new THREE.BoxGeometry(0.5, 0.5, 0.5);
  const headMaterials: THREE.MeshLambertMaterial[] = Array.from(
    { length: 6 },
    () => new THREE.MeshLambertMaterial({ color: 0xffffff })
  );
  const headMesh = new THREE.Mesh(headGeo, headMaterials);
  headMesh.position.set(0, 0.25, 0);
  headMesh.castShadow = true;
  headPivot.add(headMesh);

  const headAccessoryGroup = new THREE.Group();
  headAccessoryGroup.position.set(0, 0.25, 0);
  headPivot.add(headAccessoryGroup);

  // Torso (width 0.48, height 0.70, depth 0.26) from y=0.66 to y=1.36
  const torsoGeo = new THREE.BoxGeometry(0.48, 0.7, 0.26);
  const torsoMaterials: THREE.MeshLambertMaterial[] = Array.from(
    { length: 6 },
    () => new THREE.MeshLambertMaterial({ color: 0xffffff })
  );
  const torsoMesh = new THREE.Mesh(torsoGeo, torsoMaterials);
  torsoMesh.position.set(0, 1.01, 0);
  torsoMesh.castShadow = true;
  bodyGroup.add(torsoMesh);

  // Optional Hanbok Chima flared 3D overskirt group
  const skirtGroup = new THREE.Group();
  bodyGroup.add(skirtGroup);

  // Arms (width 0.22, height 0.68, depth 0.22), shoulder pivot at y=1.33
  const armGeo = new THREE.BoxGeometry(0.22, 0.68, 0.22);
  const armMat = new THREE.MeshLambertMaterial({ color: 0xffffff });

  const leftArmPivot = new THREE.Group();
  leftArmPivot.position.set(0.36, 1.33, 0);
  const leftArmMesh = new THREE.Mesh(armGeo, armMat);
  leftArmMesh.position.set(0, -0.3, 0);
  leftArmMesh.castShadow = true;
  leftArmPivot.add(leftArmMesh);
  bodyGroup.add(leftArmPivot);

  const rightArmPivot = new THREE.Group();
  rightArmPivot.position.set(-0.36, 1.33, 0);
  const rightArmMesh = new THREE.Mesh(armGeo, armMat);
  rightArmMesh.position.set(0, -0.3, 0);
  rightArmMesh.castShadow = true;
  rightArmPivot.add(rightArmMesh);
  bodyGroup.add(rightArmPivot);

  // Right Hand Tool Mount
  const rightHandMount = new THREE.Group();
  rightHandMount.position.set(0, -0.58, 0.12);
  rightArmPivot.add(rightHandMount);

  // Legs (width 0.23, height 0.66, depth 0.24), hip pivot at y=0.66
  const legGeo = new THREE.BoxGeometry(0.23, 0.66, 0.24);
  const legMat = new THREE.MeshLambertMaterial({ color: 0xffffff });

  const leftLegPivot = new THREE.Group();
  leftLegPivot.position.set(0.125, 0.66, 0);
  const leftLegMesh = new THREE.Mesh(legGeo, legMat);
  leftLegMesh.position.set(0, -0.33, 0);
  leftLegMesh.castShadow = true;
  leftLegPivot.add(leftLegMesh);
  bodyGroup.add(leftLegPivot);

  const rightLegPivot = new THREE.Group();
  rightLegPivot.position.set(-0.125, 0.66, 0);
  const rightLegMesh = new THREE.Mesh(legGeo, legMat);
  rightLegMesh.position.set(0, -0.33, 0);
  rightLegMesh.castShadow = true;
  rightLegPivot.add(rightLegMesh);
  bodyGroup.add(rightLegPivot);

  let frontFaceTex!: THREE.CanvasTexture;
  let blinkFaceTex!: THREE.CanvasTexture;
  const disposableTextures: THREE.Texture[] = [];

  const applyConfig = (cfg: KoreanFaceConfig) => {
    // Clear previous accessories
    while (headAccessoryGroup.children.length > 0) {
      headAccessoryGroup.remove(headAccessoryGroup.children[0]);
    }
    while (skirtGroup.children.length > 0) {
      skirtGroup.remove(skirtGroup.children[0]);
    }

    const gen = generateKoreanCharacterCanvases(cfg);
    frontFaceTex = makeTex(gen.headFront);
    blinkFaceTex = makeTex(gen.headFrontBlink);
    const leftTex = makeTex(gen.headLeft);
    const rightTex = makeTex(gen.headRight);
    const backTex = makeTex(gen.headBack);
    const topTex = makeTex(gen.headTop);
    const bottomTex = makeTex(gen.headBottom);

    const torsoFrontTex = makeTex(gen.torsoFront);
    const torsoBackTex = makeTex(gen.torsoBack);
    const torsoSideTex = makeTex(gen.torsoSide);
    const armTex = makeTex(gen.armSkin);
    const legTex = makeTex(gen.legSkin);

    disposableTextures.push(
      frontFaceTex,
      blinkFaceTex,
      leftTex,
      rightTex,
      backTex,
      topTex,
      bottomTex,
      torsoFrontTex,
      torsoBackTex,
      torsoSideTex,
      armTex,
      legTex
    );

    // Three.js BoxGeometry material order: [+X, -X, +Y, -Y, +Z (front), -Z (back)]
    headMaterials[0].map = rightTex;
    headMaterials[1].map = leftTex;
    headMaterials[2].map = topTex;
    headMaterials[3].map = bottomTex;
    headMaterials[4].map = frontFaceTex;
    headMaterials[5].map = backTex;
    headMaterials.forEach((m) => (m.needsUpdate = true));

    torsoMaterials[0].map = torsoSideTex;
    torsoMaterials[1].map = torsoSideTex;
    torsoMaterials[2].map = torsoSideTex;
    torsoMaterials[3].map = torsoSideTex;
    torsoMaterials[4].map = torsoFrontTex;
    torsoMaterials[5].map = torsoBackTex;
    torsoMaterials.forEach((m) => (m.needsUpdate = true));

    armMat.map = armTex;
    armMat.needsUpdate = true;
    legMat.map = legTex;
    legMat.needsUpdate = true;

    // Build 3D Korean Hairstyle / Headwear Accessories!
    build3DHeadAccessories(headAccessoryGroup, cfg);

    // Build 3D Hanbok Chima flared skirt layer if wearing Hanbok!
    if (
      cfg.outfitStyle === 'hanbok_pink' ||
      cfg.outfitStyle === 'hanbok_royal' ||
      cfg.outfitStyle === 'hanbok_apron'
    ) {
      const chimaColor =
        cfg.outfitStyle === 'hanbok_pink'
          ? 0xf06586
          : cfg.outfitStyle === 'hanbok_royal'
          ? 0x4b3b78
          : 0x4a7c6f;
      const trimColor =
        cfg.outfitStyle === 'hanbok_royal' ? 0xe8b94f : 0xfff0f3;

      const chimaGeo = new THREE.CylinderGeometry(0.28, 0.39, 0.72, 12);
      const chimaMat = new THREE.MeshLambertMaterial({ color: chimaColor });
      const chimaMesh = new THREE.Mesh(chimaGeo, chimaMat);
      chimaMesh.position.set(0, 0.5, 0);
      chimaMesh.scale.set(1.05, 1, 0.78);
      skirtGroup.add(chimaMesh);

      const hemGeo = new THREE.CylinderGeometry(0.385, 0.395, 0.06, 12);
      const hemMat = new THREE.MeshLambertMaterial({ color: trimColor });
      const hemMesh = new THREE.Mesh(hemGeo, hemMat);
      hemMesh.position.set(0, 0.16, 0);
      hemMesh.scale.set(1.06, 1, 0.79);
      skirtGroup.add(hemMesh);
    }
  };

  applyConfig(initialConfig);

  let nameSprite: THREE.Sprite | undefined;
  if (options?.nameFa) {
    nameSprite = createNameplateSprite(
      options.nameFa,
      options.nameKo || '',
      options.roleFa || '',
      Boolean(options.isHostile)
    );
    const extraHatOffset =
      initialConfig.hairStyle === 'joseon_gat' ||
      initialConfig.hairStyle === 'satgat_farmer' ||
      initialConfig.hairStyle === 'dokkaebi_horn'
        ? 0.32
        : 0.08;
    nameSprite.position.set(0, 2.22 + extraHatOffset, 0);
    root.add(nameSprite);
  }

  const setBlinking = (blinking: boolean) => {
    const target = blinking ? blinkFaceTex : frontFaceTex;
    if (headMaterials[4].map !== target) {
      headMaterials[4].map = target;
      headMaterials[4].needsUpdate = true;
    }
  };

  const animateWalk = (speed: number, time: number, swingProgress = 0) => {
    const clampedSpeed = Math.min(1.2, speed);
    const walkSwing = Math.sin(time * 9.5) * 0.68 * clampedSpeed;

    leftLegPivot.rotation.x = walkSwing;
    rightLegPivot.rotation.x = -walkSwing;
    leftArmPivot.rotation.x = -walkSwing * 0.85;

    if (swingProgress > 0) {
      // Mining / sword attack arm swing!
      const s = Math.sin(swingProgress * Math.PI);
      rightArmPivot.rotation.x = -1.25 * s - 0.25;
      rightArmPivot.rotation.z = -0.18 * s;
    } else {
      rightArmPivot.rotation.x = walkSwing * 0.85;
      rightArmPivot.rotation.z = 0;
    }

    // Subtle idle breathing
    const idleBob = Math.sin(time * 2.4) * 0.025;
    leftArmPivot.rotation.z = 0.05 + idleBob;
    if (swingProgress <= 0) {
      rightArmPivot.rotation.z = -0.05 - idleBob;
    }
  };

  const dispose = () => {
    headGeo.dispose();
    torsoGeo.dispose();
    armGeo.dispose();
    legGeo.dispose();
    disposableTextures.forEach((t) => t.dispose());
    headMaterials.forEach((m) => m.dispose());
    torsoMaterials.forEach((m) => m.dispose());
    armMat.dispose();
    legMat.dispose();
  };

  return {
    root,
    bodyGroup,
    headPivot,
    headMesh,
    leftArmPivot,
    rightArmPivot,
    leftLegPivot,
    rightLegPivot,
    rightHandMount,
    frontFaceTex,
    blinkFaceTex,
    headMaterials,
    nameSprite,
    setBlinking,
    updateFaceConfig: applyConfig,
    animateWalk,
    dispose,
  };
}

function build3DHeadAccessories(group: THREE.Group, cfg: KoreanFaceConfig): void {
  const hairMat = new THREE.MeshLambertMaterial({ color: cfg.hairColor });

  if (cfg.hairStyle === 'joseon_gat') {
    // Iconic Traditional Korean Black Horsehair Gat (갓)!
    const brimMat = new THREE.MeshLambertMaterial({
      color: 0x16171d,
      transparent: true,
      opacity: 0.86,
      side: THREE.DoubleSide,
    });
    const crownMat = new THREE.MeshLambertMaterial({
      color: 0x121318,
      transparent: true,
      opacity: 0.92,
    });
    const goldMat = new THREE.MeshLambertMaterial({ color: 0xe3b94b });

    const brim = new THREE.Mesh(new THREE.CylinderGeometry(0.58, 0.58, 0.025, 24), brimMat);
    brim.position.set(0, 0.25, 0);
    group.add(brim);

    const crown = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.25, 0.34, 18), crownMat);
    crown.position.set(0, 0.42, 0);
    group.add(crown);

    const topRing = new THREE.Mesh(new THREE.CylinderGeometry(0.225, 0.225, 0.022, 18), goldMat);
    topRing.position.set(0, 0.58, 0);
    group.add(topRing);
  } else if (cfg.hairStyle === 'satgat_farmer') {
    // Traditional Korean Conical Woven Reed Hat (삿갓)!
    const bambooMat = new THREE.MeshLambertMaterial({ color: 0xd9bf86 });
    const rimMat = new THREE.MeshLambertMaterial({ color: 0xb59659 });
    const cone = new THREE.Mesh(new THREE.ConeGeometry(0.58, 0.32, 16), bambooMat);
    cone.position.set(0, 0.36, 0);
    group.add(cone);

    const rim = new THREE.Mesh(new THREE.CylinderGeometry(0.58, 0.58, 0.025, 16), rimMat);
    rim.position.set(0, 0.21, 0);
    group.add(rim);
  } else if (cfg.hairStyle === 'binyeo_bun') {
    // 3D Low Nape Bun (쪽진머리) + Jade Binyeo Hairpin (비녀) + Coral Ornament!
    const bun = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.2, 0.16), hairMat);
    bun.position.set(0, -0.08, -0.28);
    group.add(bun);

    const jadeMat = new THREE.MeshLambertMaterial({ color: 0x67caa8 });
    const pin = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.46, 10), jadeMat);
    pin.rotation.z = Math.PI / 2;
    pin.position.set(0, -0.08, -0.3);
    group.add(pin);

    const coralTip = new THREE.Mesh(
      new THREE.SphereGeometry(0.038, 10, 10),
      new THREE.MeshLambertMaterial({ color: 0xe55b78 })
    );
    coralTip.position.set(0.23, -0.08, -0.3);
    group.add(coralTip);
  } else if (cfg.hairStyle === 'seethrough_long') {
    // 3D Long Silky Back Hair + Crimson Daenggi (댕기) Ribbon!
    const backHair = new THREE.Mesh(new THREE.BoxGeometry(0.52, 0.42, 0.08), hairMat);
    backHair.position.set(0, -0.24, -0.24);
    group.add(backHair);

    const daenggi = new THREE.Mesh(
      new THREE.BoxGeometry(0.12, 0.36, 0.04),
      new THREE.MeshLambertMaterial({ color: 0xc92a3e })
    );
    daenggi.position.set(0, -0.26, -0.29);
    group.add(daenggi);
  } else if (cfg.hairStyle === 'comma_twoblock' || cfg.hairStyle === 'student_cut') {
    // Subtle 3D Top Hair Volume Cap (Korean Two-Block Fluffy Top!)
    const topCap = new THREE.Mesh(new THREE.BoxGeometry(0.53, 0.13, 0.53), hairMat);
    topCap.position.set(0, 0.23, 0.01);
    group.add(topCap);
  } else if (cfg.hairStyle === 'halmeoni_perm') {
    // Fluffy 3D Curly Perm Crown for Grandma Soon-ja!
    const topPuff = new THREE.Mesh(new THREE.BoxGeometry(0.56, 0.16, 0.55), hairMat);
    topPuff.position.set(0, 0.24, 0);
    group.add(topPuff);
  } else if (cfg.hairStyle === 'dokkaebi_horn') {
    // Korean Folklore Dokkaebi Golden Horns!
    const hornMat = new THREE.MeshLambertMaterial({ color: 0xf2c94c });
    for (const sx of [-0.13, 0.13]) {
      const horn = new THREE.Mesh(new THREE.ConeGeometry(0.055, 0.22, 8), hornMat);
      horn.position.set(sx, 0.33, 0.16);
      horn.rotation.x = 0.28;
      horn.rotation.z = sx < 0 ? 0.2 : -0.2;
      group.add(horn);
    }
  }

  // 3D Round Seoul Glasses Rim Accent
  if (cfg.glasses !== 'none') {
    const rimMat = new THREE.MeshLambertMaterial({
      color: cfg.glasses === 'tinted_idol' ? 0xd4af37 : 0x282c34,
    });
    for (const gx of [-0.105, 0.105]) {
      const torus = new THREE.Mesh(new THREE.TorusGeometry(0.068, 0.009, 8, 20), rimMat);
      torus.position.set(gx, -0.03, 0.256);
      group.add(torus);
    }
  }
}

export function buildHeldItemMesh(
  itemId: InventoryItemId | 'dokkaebi_club' | null,
  blockMaterialGetter?: (blockId: number) => THREE.Material | THREE.Material[]
): THREE.Object3D | null {
  if (itemId === null || itemId === 0) return null;

  const group = new THREE.Group();

  if (typeof itemId === 'number' && blockMaterialGetter) {
    const geo = new THREE.BoxGeometry(0.28, 0.28, 0.28);
    const mesh = new THREE.Mesh(geo, blockMaterialGetter(itemId));
    mesh.position.set(0, -0.02, 0.08);
    group.add(mesh);
    return group;
  }

  const woodMat = new THREE.MeshLambertMaterial({ color: 0x7c5333 });

  if (itemId === 'diamond_pickaxe') {
    const handle = new THREE.Mesh(new THREE.BoxGeometry(0.045, 0.52, 0.045), woodMat);
    handle.rotation.x = Math.PI / 4;
    handle.position.set(0, 0.04, 0.12);
    group.add(handle);

    const headMat = new THREE.MeshLambertMaterial({ color: 0x3be8e0 });
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.055, 0.07, 0.38), headMat);
    head.rotation.x = Math.PI / 4;
    head.position.set(0, 0.2, 0.28);
    group.add(head);
    return group;
  }

  if (itemId === 'iron_axe') {
    const handle = new THREE.Mesh(new THREE.BoxGeometry(0.045, 0.48, 0.045), woodMat);
    handle.rotation.x = Math.PI / 4;
    handle.position.set(0, 0.04, 0.12);
    group.add(handle);

    const bladeMat = new THREE.MeshLambertMaterial({ color: 0xdce3ec });
    const blade = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.18, 0.2), bladeMat);
    blade.rotation.x = Math.PI / 4;
    blade.position.set(0, 0.16, 0.28);
    group.add(blade);
    return group;
  }

  if (itemId === 'joseon_sword') {
    // Korean Hwandudaedo (환두대도) Ring-Pommel Royal Sword!
    const hiltMat = new THREE.MeshLambertMaterial({ color: 0x9e2432 });
    const goldMat = new THREE.MeshLambertMaterial({ color: 0xe8b94f });
    const steelMat = new THREE.MeshLambertMaterial({ color: 0xeef4ff });

    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.04, 0.012, 8, 14), goldMat);
    ring.position.set(0, -0.06, -0.04);
    ring.rotation.y = Math.PI / 2;
    group.add(ring);

    const grip = new THREE.Mesh(new THREE.BoxGeometry(0.045, 0.045, 0.16), hiltMat);
    grip.position.set(0, -0.02, 0.06);
    group.add(grip);

    const guard = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.14, 0.03), goldMat);
    guard.position.set(0, 0, 0.14);
    group.add(guard);

    const blade = new THREE.Mesh(new THREE.BoxGeometry(0.025, 0.065, 0.58), steelMat);
    blade.position.set(0, 0.06, 0.43);
    blade.rotation.x = -0.15;
    group.add(blade);
    return group;
  }

  if (itemId === 'dokkaebi_club') {
    // Korean Dokkaebi Bangmangi (도깨비방망이) Spiked Club!
    const clubMat = new THREE.MeshLambertMaterial({ color: 0x5c3422 });
    const spikeMat = new THREE.MeshLambertMaterial({ color: 0xf2c94c });
    const club = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.035, 0.56, 8), clubMat);
    club.rotation.x = Math.PI / 2.4;
    club.position.set(0, 0.05, 0.24);
    group.add(club);

    for (const angle of [0, 2.1, 4.2]) {
      const spike = new THREE.Mesh(new THREE.ConeGeometry(0.025, 0.07, 6), spikeMat);
      spike.position.set(Math.cos(angle) * 0.08, 0.1 + Math.sin(angle) * 0.05, 0.34);
      group.add(spike);
    }
    return group;
  }

  if (itemId === 'kimbap') {
    // Cute 3D Kimbap Roll (김밥)!
    const seaweed = new THREE.Mesh(
      new THREE.CylinderGeometry(0.075, 0.075, 0.22, 12),
      new THREE.MeshLambertMaterial({ color: 0x1c261e })
    );
    seaweed.rotation.x = Math.PI / 2;
    seaweed.position.set(0, 0, 0.12);
    group.add(seaweed);
    return group;
  }

  if (itemId === 'tteokbokki') {
    const bowl = new THREE.Mesh(
      new THREE.CylinderGeometry(0.11, 0.075, 0.1, 12),
      new THREE.MeshLambertMaterial({ color: 0xd93829 })
    );
    bowl.position.set(0, 0, 0.12);
    group.add(bowl);
    return group;
  }

  return null;
}

function createNameplateSprite(
  nameFa: string,
  nameKo: string,
  roleFa: string,
  isHostile: boolean
): THREE.Sprite {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 128;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = isHostile ? 'rgba(88, 18, 24, 0.82)' : 'rgba(15, 23, 38, 0.78)';
  ctx.beginPath();
  ctx.roundRect(24, 14, 464, 98, 22);
  ctx.fill();

  ctx.strokeStyle = isHostile ? 'rgba(242, 110, 110, 0.85)' : 'rgba(255, 206, 138, 0.65)';
  ctx.lineWidth = 3;
  ctx.stroke();

  ctx.textAlign = 'center';
  ctx.fillStyle = '#FFFFFF';
  ctx.font = 'bold 34px Vazirmatn, Tahoma, sans-serif';
  ctx.fillText(`${nameFa}  •  ${nameKo}`, 256, 58);

  ctx.fillStyle = isHostile ? '#FFB4B4' : '#FAD089';
  ctx.font = '24px Vazirmatn, Tahoma, sans-serif';
  ctx.fillText(roleFa, 256, 94);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.SpriteMaterial({
    map: tex,
    transparent: true,
    depthTest: true,
  });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(1.9, 0.48, 1);
  return sprite;
}
