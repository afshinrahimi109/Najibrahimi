import * as THREE from 'three';
import { soundFX } from '../audio/SoundFX';
import {
  buildHeldItemMesh,
  buildKoreanCharacterRig,
  CharacterRig,
} from '../character/KoreanCharacterMesh';
import { KOREAN_CHARACTER_PRESETS } from '../character/KoreanPresets';
import { renderCharacterPortraitDataUrl } from '../character/KoreanSkinGenerator';
import {
  ALL_CREATIVE_ITEMS,
  BLOCK_IDS,
  CRAFTING_RECIPES,
  getItemMeta,
} from '../data/items';
import {
  ActiveModal,
  BlockId,
  CameraMode,
  CharacterPreset,
  CraftingRecipe,
  GameMode,
  HudState,
  InventoryItemId,
  InventorySlot,
  KoreanFaceConfig,
  NpcStatusSnapshot,
  TradeOffer,
} from '../types/game';
import { BlockTextureSystem, getBlockTextureSystem } from '../world/BlockTextures';
import {
  RaycastHit,
  VoxelWorld,
  WATER_LEVEL,
  WORLD_DEPTH,
  WORLD_WIDTH,
} from '../world/VoxelWorld';

interface NpcEntity {
  id: string;
  preset: CharacterPreset;
  rig: CharacterRig;
  pos: THREE.Vector3;
  vel: THREE.Vector3;
  yaw: number;
  targetYaw: number;
  aiTimer: number;
  moving: boolean;
  blinkTimer: number;
  isBlinking: boolean;
  isFollowing: boolean;
  hp: number;
  maxHp: number;
  hurtFlash: number;
  attackCooldown: number;
  swingAnim: number;
}

interface DroppedPickup {
  itemId: InventoryItemId;
  count: number;
  mesh: THREE.Object3D;
  pos: THREE.Vector3;
  vel: THREE.Vector3;
  age: number;
}

interface PrimedTnt {
  mesh: THREE.Mesh;
  pos: THREE.Vector3;
  vel: THREE.Vector3;
  fuse: number;
}

interface Particle {
  mesh: THREE.Mesh;
  vel: THREE.Vector3;
  life: number;
  maxLife: number;
  gravity: number;
}

export class KCraftEngine {
  private readonly container: HTMLElement;
  private readonly onHudUpdate: (state: HudState) => void;

  public readonly texSys: BlockTextureSystem;
  public readonly world: VoxelWorld;

  private scene!: THREE.Scene;
  private camera!: THREE.PerspectiveCamera;
  private fpScene!: THREE.Scene;
  private fpCamera!: THREE.PerspectiveCamera;
  private renderer!: THREE.WebGLRenderer;

  private ambientLight!: THREE.AmbientLight;
  private sunLight!: THREE.DirectionalLight;
  private hemiLight!: THREE.HemisphereLight;
  private sunMesh!: THREE.Mesh;
  private moonMesh!: THREE.Mesh;
  private highlightBox!: THREE.LineSegments;
  private crackBox!: THREE.Mesh;

  // Player state
  private playerPos = new THREE.Vector3(48.5, 18.2, 51.5);
  private playerVel = new THREE.Vector3(0, 0, 0);
  private playerYaw = Math.PI; // Facing north toward the Grand Hanok & NPCs!
  private playerPitch = -0.06;
  private onGround = false;

  private playerPreset: CharacterPreset = KOREAN_CHARACTER_PRESETS[0];
  private playerFace: KoreanFaceConfig = { ...KOREAN_CHARACTER_PRESETS[0].face };
  private playerPortraitUrl = '';
  private playerRig!: CharacterRig;
  private playerBlinkTimer = 2.5;
  private playerIsBlinking = false;
  private playerSwingAnim = 0;

  // First-person right arm & held item
  private fpArmGroup!: THREE.Group;
  private fpHeldMount!: THREE.Group;
  private fpArmSleeveMesh!: THREE.Mesh;
  private fpArmHandMesh!: THREE.Mesh;

  // Gameplay & HUD state
  private started = false;
  private activeModal: ActiveModal = 'start';
  private cameraMode: CameraMode = 'first_person';
  private gameMode: GameMode = 'survival';

  private health = 20;
  private maxHealth = 20;
  private hunger = 20;
  private maxHunger = 20;
  private hungerTick = 0;

  private hotbarIndex = 0;
  private hotbar: Array<InventorySlot | null> = Array(9).fill(null);
  private inventory: Array<InventorySlot | null> = Array(18).fill(null);

  // Time of day: 0..1 (0.25 = noon, 0.52 = sunset, 0.75 = midnight)
  private timeOfDay = 0.22;
  private dayCount = 1;

  // Interaction & Mining
  private keys = new Set<string>();
  private mouseDownLeft = false;
  private draggingLook = false;
  private lastMouseX = 0;
  private lastMouseY = 0;
  private lookTouchId: number | null = null;
  private lastTouchX = 0;
  private lastTouchY = 0;
  private pointerLocked = false;

  private currentRayHit: RaycastHit | null = null;
  private miningBlockKey = '';
  private miningElapsed = 0;
  private miningDuration = 0.5;
  private digSoundTimer = 0;

  // Entities
  private npcs: NpcEntity[] = [];
  private pickups: DroppedPickup[] = [];
  private primedTnts: PrimedTnt[] = [];
  private particles: Particle[] = [];
  private cherryPetals: THREE.Points | null = null;

  private activeDialogNpcId: string | null = null;
  private nearbyNpcId: string | null = null;

  private dokkaebiDefeated = 0;
  private blocksMined = 0;
  private blocksPlaced = 0;
  private dokkaebiSpawnTimer = 8;

  private toastMessage: string | null = null;
  private toastTimeout: number | null = null;

  // Loop & perf
  private rafId = 0;
  private lastFrameTime = performance.now();
  private elapsedTotal = 0;
  private fps = 60;
  private fpsFrames = 0;
  private fpsTimer = 0;
  private hudEmitTimer = 0;
  private disposed = false;

  // Mobile virtual joystick vector
  public mobileMoveX = 0;
  public mobileMoveZ = 0;
  public mobileJumping = false;

  constructor(container: HTMLElement, onHudUpdate: (state: HudState) => void) {
    this.container = container;
    this.onHudUpdate = onHudUpdate;

    this.texSys = getBlockTextureSystem();
    this.world = new VoxelWorld(this.texSys);

    this.initScene();
    this.initStarterInventory();
    this.initPlayerRig();
    this.spawnVillageKoreanCharacters();
    this.initCherryBlossomParticles();
    this.bindEvents();

    // Ensure safe ground spawn in front of Grand Hanok Plaza
    const spawnY = this.world.getSurfaceY(48, 51);
    this.playerPos.set(48.5, spawnY + 0.05, 51.5);
    this.playerPortraitUrl = renderCharacterPortraitDataUrl(this.playerFace);

    this.emitHudState();
    this.lastFrameTime = performance.now();
    this.loop(this.lastFrameTime);
  }

  private initScene(): void {
    const w = this.container.clientWidth || window.innerWidth;
    const h = this.container.clientHeight || window.innerHeight;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x84c8f8);
    this.scene.fog = new THREE.FogExp2(0x98d2fa, 0.0115);

    this.camera = new THREE.PerspectiveCamera(72, w / h, 0.1, 220);

    // Separate overlay scene for crisp non-clipping 1st-person Minecraft arm & tool!
    this.fpScene = new THREE.Scene();
    this.fpCamera = new THREE.PerspectiveCamera(60, w / h, 0.05, 10);
    const fpAmb = new THREE.AmbientLight(0xffffff, 0.85);
    const fpDir = new THREE.DirectionalLight(0xfff5e4, 0.75);
    fpDir.position.set(2, 4, 3);
    this.fpScene.add(fpAmb, fpDir);

    try {
      this.renderer = new THREE.WebGLRenderer({
        antialias: true,
        powerPreference: 'high-performance',
      });
    } catch {
      this.renderer = new THREE.WebGLRenderer({ antialias: false });
    }
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.autoClear = false;
    this.container.appendChild(this.renderer.domElement);

    // World lighting
    this.ambientLight = new THREE.AmbientLight(0xffffff, 0.62);
    this.hemiLight = new THREE.HemisphereLight(0xbde4ff, 0x6b8258, 0.42);
    this.sunLight = new THREE.DirectionalLight(0xfff4dc, 0.92);
    this.sunLight.position.set(40, 75, 30);
    this.scene.add(this.ambientLight, this.hemiLight, this.sunLight);

    // Blocky Minecraft Sun & Moon
    this.sunMesh = new THREE.Mesh(
      new THREE.BoxGeometry(9, 9, 9),
      new THREE.MeshBasicMaterial({ color: 0xffe98a })
    );
    this.moonMesh = new THREE.Mesh(
      new THREE.BoxGeometry(7.5, 7.5, 7.5),
      new THREE.MeshBasicMaterial({ color: 0xe6f0ff })
    );
    this.scene.add(this.sunMesh, this.moonMesh);

    this.scene.add(this.world.worldGroup);

    // Block Target Selection Wireframe Box
    const edgeGeo = new THREE.EdgesGeometry(new THREE.BoxGeometry(1.008, 1.008, 1.008));
    this.highlightBox = new THREE.LineSegments(
      edgeGeo,
      new THREE.LineBasicMaterial({ color: 0x11151c })
    );
    this.highlightBox.visible = false;
    this.scene.add(this.highlightBox);

    // Block Breaking Crack Overlay Cube
    this.crackBox = new THREE.Mesh(
      new THREE.BoxGeometry(1.014, 1.014, 1.014),
      new THREE.MeshBasicMaterial({
        color: 0x1a1a1a,
        transparent: true,
        opacity: 0,
        wireframe: true,
      })
    );
    this.crackBox.visible = false;
    this.scene.add(this.crackBox);
  }

  private initStarterInventory(): void {
    this.hotbar = [
      { id: 'diamond_pickaxe', count: 1 },
      { id: 'joseon_sword', count: 1 },
      { id: 'iron_axe', count: 1 },
      { id: BLOCK_IDS.HANOK_TILE, count: 32 },
      { id: BLOCK_IDS.HANJI_WALL, count: 32 },
      { id: BLOCK_IDS.RED_PILLAR, count: 24 },
      { id: BLOCK_IDS.LANTERN, count: 16 },
      { id: 'kimbap', count: 8 },
      { id: BLOCK_IDS.OAK_PLANKS, count: 32 },
    ];

    this.inventory = [
      { id: BLOCK_IDS.GRASS, count: 32 },
      { id: BLOCK_IDS.COBBLESTONE, count: 32 },
      { id: BLOCK_IDS.BRICK, count: 32 },
      { id: BLOCK_IDS.CHERRY_LEAVES, count: 24 },
      { id: BLOCK_IDS.GLASS, count: 24 },
      { id: BLOCK_IDS.OAK_LOG, count: 16 },
      { id: BLOCK_IDS.CRAFTING_TABLE, count: 2 },
      { id: BLOCK_IDS.TNT, count: 6 },
      { id: 'tteokbokki', count: 5 },
      null,
      null,
      null,
      null,
      null,
      null,
      null,
      null,
      null,
    ];
  }

  private initPlayerRig(): void {
    this.playerRig = buildKoreanCharacterRig(this.playerFace);
    this.scene.add(this.playerRig.root);

    // Build 1st-person right arm & sleeve
    this.fpArmGroup = new THREE.Group();
    this.fpArmGroup.position.set(0.52, -0.46, -0.72);

    this.fpArmSleeveMesh = new THREE.Mesh(
      new THREE.BoxGeometry(0.18, 0.42, 0.18),
      new THREE.MeshLambertMaterial({ color: 0x39558f })
    );
    this.fpArmSleeveMesh.rotation.x = -0.95;
    this.fpArmSleeveMesh.rotation.z = 0.22;
    this.fpArmGroup.add(this.fpArmSleeveMesh);

    this.fpArmHandMesh = new THREE.Mesh(
      new THREE.BoxGeometry(0.16, 0.18, 0.16),
      new THREE.MeshLambertMaterial({ color: 0xfce3d2 })
    );
    this.fpArmHandMesh.position.set(-0.04, 0.12, -0.18);
    this.fpArmHandMesh.rotation.x = -0.95;
    this.fpArmGroup.add(this.fpArmHandMesh);

    this.fpHeldMount = new THREE.Group();
    this.fpHeldMount.position.set(-0.06, 0.14, -0.22);
    this.fpArmGroup.add(this.fpHeldMount);

    this.fpScene.add(this.fpArmGroup);
    this.refreshHeldItemMeshes();
  }

  private refreshHeldItemMeshes(): void {
    while (this.playerRig.rightHandMount.children.length > 0) {
      this.playerRig.rightHandMount.remove(this.playerRig.rightHandMount.children[0]);
    }
    while (this.fpHeldMount.children.length > 0) {
      this.fpHeldMount.remove(this.fpHeldMount.children[0]);
    }

    const activeSlot = this.hotbar[this.hotbarIndex];
    if (!activeSlot) return;

    const worldHeld = buildHeldItemMesh(activeSlot.id, (b) =>
      this.texSys.getSingleBlockMaterials(b)
    );
    if (worldHeld) {
      this.playerRig.rightHandMount.add(worldHeld);
    }

    const fpHeld = buildHeldItemMesh(activeSlot.id, (b) =>
      this.texSys.getSingleBlockMaterials(b)
    );
    if (fpHeld) {
      fpHeld.scale.setScalar(1.12);
      fpHeld.rotation.set(0.3, -0.45, 0.1);
      this.fpHeldMount.add(fpHeld);
    }
  }

  private spawnVillageKoreanCharacters(): void {
    // Spawn all 9 friendly Korean characters around the Hanok Plaza, Market, Bridge & Cave!
    const placements: Array<{
      presetId: string;
      x: number;
      z: number;
      yaw: number;
      heldItem: InventoryItemId | null;
    }> = [
      { presetId: 'seoyeon', x: 46.5, z: 45.2, yaw: 0.2, heldItem: BLOCK_IDS.CHERRY_LEAVES },
      { presetId: 'minjun', x: 50.5, z: 45.5, yaw: -0.3, heldItem: BLOCK_IDS.LANTERN },
      { presetId: 'jihoon', x: 48.5, z: 41.0, yaw: 0, heldItem: 'joseon_sword' },
      { presetId: 'halmeoni', x: 38.2, z: 46.5, yaw: Math.PI / 2, heldItem: 'kimbap' },
      { presetId: 'doyun', x: 57.5, z: 46.8, yaw: -Math.PI / 2, heldItem: 'diamond_pickaxe' },
      { presetId: 'haeun', x: 51.8, z: 51.5, yaw: -2.4, heldItem: BLOCK_IDS.HANOK_TILE },
      { presetId: 'subin', x: 44.2, z: 40.5, yaw: 0.4, heldItem: BLOCK_IDS.HANJI_WALL },
      { presetId: 'harabeoji', x: 62.5, z: 32.5, yaw: -0.8, heldItem: 'iron_axe' },
      { presetId: 'taeyang', x: 48.5, z: 57.2, yaw: Math.PI, heldItem: BLOCK_IDS.OAK_LOG },
    ];

    for (const spot of placements) {
      const preset = KOREAN_CHARACTER_PRESETS.find((p) => p.id === spot.presetId);
      if (!preset) continue;
      this.spawnNpcFromPreset(preset, spot.x, spot.z, spot.yaw, spot.heldItem);
    }
  }

  private spawnNpcFromPreset(
    preset: CharacterPreset,
    x: number,
    z: number,
    yaw = 0,
    heldItem: InventoryItemId | 'dokkaebi_club' | null = null
  ): NpcEntity {
    const rig = buildKoreanCharacterRig(preset.face, {
      nameFa: preset.nameFa,
      nameKo: preset.nameKo,
      roleFa: preset.roleFa,
      isHostile: preset.isHostile,
    });

    if (heldItem) {
      const itemMesh = buildHeldItemMesh(heldItem, (b) =>
        this.texSys.getSingleBlockMaterials(b)
      );
      if (itemMesh) rig.rightHandMount.add(itemMesh);
    }

    const sy = this.world.getSurfaceY(x, z);
    const pos = new THREE.Vector3(x, sy + 0.02, z);
    rig.root.position.copy(pos);
    rig.bodyGroup.rotation.y = yaw;
    this.scene.add(rig.root);

    const npc: NpcEntity = {
      id: `${preset.id}_${Math.random().toString(36).slice(2, 7)}`,
      preset,
      rig,
      pos,
      vel: new THREE.Vector3(),
      yaw,
      targetYaw: yaw,
      aiTimer: 1 + Math.random() * 3,
      moving: false,
      blinkTimer: 1.5 + Math.random() * 3.5,
      isBlinking: false,
      isFollowing: false,
      hp: preset.isHostile ? 22 : 30,
      maxHp: preset.isHostile ? 22 : 30,
      hurtFlash: 0,
      attackCooldown: 0,
      swingAnim: 0,
    };

    this.npcs.push(npc);
    return npc;
  }

  private initCherryBlossomParticles(): void {
    const count = 220;
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      positions[i * 3] = 20 + Math.random() * 56;
      positions[i * 3 + 1] = 16 + Math.random() * 18;
      positions[i * 3 + 2] = 22 + Math.random() * 54;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const mat = new THREE.PointsMaterial({
      color: 0xffb7ce,
      size: 0.24,
      transparent: true,
      opacity: 0.88,
    });
    this.cherryPetals = new THREE.Points(geo, mat);
    this.scene.add(this.cherryPetals);
  }

  // ==================== PUBLIC CONTROLS FOR UI ====================

  public startGame(): void {
    this.started = true;
    this.activeModal = 'none';
    this.requestCanvasPointerLock();
    this.showToast(`به دهکده کی‌کرفت خوش آمدی، ${this.playerPreset.nameFa} (${this.playerPreset.nameKo})!`);
    soundFX.playGreetingChime();
    this.emitHudState();
  }

  public requestCanvasPointerLock(): void {
    try {
      const el = this.renderer.domElement;
      if (document.pointerLockElement !== el && el.requestPointerLock) {
        const res = el.requestPointerLock() as unknown as Promise<void> | undefined;
        if (res && typeof res.catch === 'function') {
          res.catch(() => {});
        }
      }
    } catch {
      // Safe fallback: drag-to-look works automatically when pointer lock is unavailable
    }
  }

  public exitPointerLock(): void {
    try {
      if (document.pointerLockElement) {
        document.exitPointerLock();
      }
    } catch {
      // ignore
    }
  }

  public setModal(modal: ActiveModal): void {
    this.activeModal = modal;
    if (modal !== 'none') {
      this.mouseDownLeft = false;
      this.exitPointerLock();
    } else if (this.started) {
      this.requestCanvasPointerLock();
    }
    this.emitHudState();
  }

  public selectCharacterPreset(preset: CharacterPreset): void {
    this.playerPreset = preset;
    this.playerFace = { ...preset.face };
    this.applyPlayerAppearance();
  }

  public updatePlayerFace(partial: Partial<KoreanFaceConfig>): void {
    this.playerFace = { ...this.playerFace, ...partial };
    this.applyPlayerAppearance();
  }

  private applyPlayerAppearance(): void {
    this.playerRig.updateFaceConfig(this.playerFace);
    this.playerPortraitUrl = renderCharacterPortraitDataUrl(this.playerFace);

    // Sync 1st-person sleeve & hand colors with chosen Korean skin & outfit!
    const skinHexMap: Record<string, number> = {
      porcelain: 0xfce3d2,
      warm_ivory: 0xf8d7be,
      natural_peach: 0xf1c8aa,
      honey_warm: 0xe6b794,
      dokkaebi_bronze: 0xd99e79,
    };
    const sleeveHexMap: Record<string, number> = {
      seoul_street: 0x39558f,
      hanbok_pink: 0xfff0f4,
      hanbok_royal: 0xdce9fa,
      joseon_guard: 0x9e2432,
      halmeoni_vest: 0xf6efe6,
      carpenter_hemp: 0x8c7254,
      student_hoodie: 0x294e66,
      hanbok_apron: 0xfce4c8,
      farmer_linen: 0x5f8758,
      dokkaebi_armor: 0xd98a2b,
    };
    (this.fpArmHandMesh.material as THREE.MeshLambertMaterial).color.setHex(
      skinHexMap[this.playerFace.skinTone] ?? 0xfce3d2
    );
    (this.fpArmSleeveMesh.material as THREE.MeshLambertMaterial).color.setHex(
      sleeveHexMap[this.playerFace.outfitStyle] ?? 0x39558f
    );

    this.refreshHeldItemMeshes();
    this.emitHudState();
  }

  public cycleCameraMode(): void {
    const order: CameraMode[] = ['first_person', 'third_back', 'third_front'];
    const next = order[(order.indexOf(this.cameraMode) + 1) % order.length];
    this.cameraMode = next;
    const labels: Record<CameraMode, string> = {
      first_person: 'دوربین اول‌شخص ماین‌کرفت',
      third_back: 'دوربین سوم‌شخص (پشت سر)',
      third_front: 'دوربین سلفی چهره کره‌ای!',
    };
    this.showToast(labels[next]);
    this.emitHudState();
  }

  public toggleGameMode(): void {
    this.gameMode = this.gameMode === 'survival' ? 'creative' : 'survival';
    if (this.gameMode === 'creative') {
      this.health = this.maxHealth;
      this.hunger = this.maxHunger;
      this.showToast('حالت خلاقیت فعال شد: بلوک بی‌نهایت و شکستن فوری!');
    } else {
      this.showToast('حالت بقا (Survival) فعال شد!');
    }
    this.emitHudState();
  }

  public toggleDayNight(): void {
    const currentlyNight = this.timeOfDay > 0.56 && this.timeOfDay < 0.94;
    this.timeOfDay = currentlyNight ? 0.23 : 0.68;
    this.showToast(
      currentlyNight
        ? 'طلوع آفتاب بهاری در دهکده کره‌ای ☀️'
        : 'شب فانوس‌های ابریشمی فرا رسید 🏮'
    );
    this.emitHudState();
  }

  public spawnDokkaebiChallenge(): void {
    const dokkaebiPreset = KOREAN_CHARACTER_PRESETS.find((p) => p.id === 'dokkaebi');
    if (!dokkaebiPreset) return;
    const angle = this.playerYaw + (Math.random() - 0.5) * 1.1;
    const dist = 9 + Math.random() * 4;
    const sx = Math.max(8, Math.min(WORLD_WIDTH - 8, this.playerPos.x - Math.sin(angle) * dist));
    const sz = Math.max(8, Math.min(WORLD_DEPTH - 8, this.playerPos.z - Math.cos(angle) * dist));
    this.spawnNpcFromPreset(dokkaebiPreset, sx, sz, angle + Math.PI, 'dokkaebi_club');
    this.showToast('جنگجوی افسانه‌ای دوکه‌بی (도깨비) وارد میدان شد! ⚔️');
    soundFX.playSwordSwing();
    this.emitHudState();
  }

  public teleportToVillage(): void {
    const sy = this.world.getSurfaceY(48, 51);
    this.playerPos.set(48.5, sy + 0.1, 51.5);
    this.playerVel.set(0, 0, 0);
    this.playerYaw = Math.PI;
    this.playerPitch = -0.05;
    this.showToast('بازگشت به میدان اصلی عمارت هانوک!');
    this.emitHudState();
  }

  public selectHotbarSlot(index: number): void {
    if (index < 0 || index >= 9) return;
    this.hotbarIndex = index;
    this.miningElapsed = 0;
    this.refreshHeldItemMeshes();
    this.emitHudState();
  }

  public equipCreativeItemToHotbar(itemId: InventoryItemId): void {
    const meta = getItemMeta(itemId);
    const count = meta.category === 'tool' ? 1 : 64;
    this.hotbar[this.hotbarIndex] = { id: itemId, count };
    this.refreshHeldItemMeshes();
    soundFX.playPickup();
    this.showToast(`«${meta.nameFa}» در اسلات ${this.hotbarIndex + 1} قرار گرفت`);
    this.emitHudState();
  }

  public swapInventoryWithHotbar(invIdx: number): void {
    if (invIdx < 0 || invIdx >= this.inventory.length) return;
    const temp = this.hotbar[this.hotbarIndex];
    this.hotbar[this.hotbarIndex] = this.inventory[invIdx];
    this.inventory[invIdx] = temp;
    this.refreshHeldItemMeshes();
    soundFX.playPickup();
    this.emitHudState();
  }

  public craftRecipe(recipe: CraftingRecipe): void {
    if (this.gameMode !== 'creative') {
      for (const ing of recipe.ingredients) {
        if (this.countItem(ing.id) < ing.count) {
          this.showToast('منابع کافی برای ساخت این آیتم نداری!');
          return;
        }
      }
      for (const ing of recipe.ingredients) {
        this.consumeItem(ing.id, ing.count);
      }
    }
    this.addItemToInventory(recipe.resultId, recipe.resultCount);
    soundFX.playPickup();
    this.showToast(`ساخته شد: ${recipe.nameFa}`);
    this.emitHudState();
  }

  public executeNpcTrade(offer: TradeOffer): void {
    if (this.gameMode !== 'creative') {
      if (this.countItem(offer.giveId) < offer.giveCount) {
        const needed = getItemMeta(offer.giveId).nameFa;
        this.showToast(`برای این معامله به ${offer.giveCount} عدد «${needed}» نیاز داری!`);
        return;
      }
      this.consumeItem(offer.giveId, offer.giveCount);
    }
    this.addItemToInventory(offer.receiveId, offer.receiveCount);
    soundFX.playGreetingChime();
    const got = getItemMeta(offer.receiveId).nameFa;
    this.showToast(`معامله موفق! ${offer.receiveCount} عدد «${got}» دریافت کردی!`);
    this.emitHudState();
  }

  public toggleNpcFollow(entityId: string): void {
    const npc = this.npcs.find((n) => n.id === entityId);
    if (!npc || npc.preset.isHostile) return;
    npc.isFollowing = !npc.isFollowing;
    soundFX.playGreetingChime();
    this.showToast(
      npc.isFollowing
        ? `${npc.preset.nameFa} (${npc.preset.nameKo}) حالا همراه شماست!`
        : `${npc.preset.nameFa} در همین حوالی به گشت‌وگذار ادامه می‌دهد.`
    );
    this.emitHudState();
  }

  public triggerPrimaryActionTap(): void {
    // Useful for mobile/touch button
    this.playerSwingAnim = 1;
    if (this.tryAttackOrInteractEntity(true)) return;
    if (this.currentRayHit) {
      if (this.currentRayHit.blockId === BLOCK_IDS.TNT) {
        this.igniteTntAt(
          this.currentRayHit.bx,
          this.currentRayHit.by,
          this.currentRayHit.bz
        );
        return;
      }
      this.breakVoxelBlock(
        this.currentRayHit.bx,
        this.currentRayHit.by,
        this.currentRayHit.bz,
        this.currentRayHit.blockId
      );
    }
  }

  public triggerSecondaryAction(): void {
    this.handleRightClickAction();
  }

  public rotateCameraBy(dYaw: number, dPitch: number): void {
    this.playerYaw -= dYaw;
    this.playerPitch = Math.max(
      -Math.PI / 2 + 0.05,
      Math.min(Math.PI / 2 - 0.05, this.playerPitch - dPitch)
    );
  }

  public countItem(id: InventoryItemId): number {
    let total = 0;
    for (const s of [...this.hotbar, ...this.inventory]) {
      if (s && s.id === id) total += s.count;
    }
    return total;
  }

  private consumeItem(id: InventoryItemId, amount: number): void {
    let rem = amount;
    const allLists = [this.hotbar, this.inventory];
    for (const list of allLists) {
      for (let i = 0; i < list.length && rem > 0; i++) {
        const slot = list[i];
        if (slot && slot.id === id) {
          const take = Math.min(rem, slot.count);
          slot.count -= take;
          rem -= take;
          if (slot.count <= 0) list[i] = null;
        }
      }
    }
    this.refreshHeldItemMeshes();
  }

  private addItemToInventory(id: InventoryItemId, amount: number): void {
    const meta = getItemMeta(id);
    const maxStack = meta.category === 'tool' ? 1 : 99;
    let rem = amount;

    // 1. Stack into existing hotbar / inventory slots
    if (maxStack > 1) {
      for (const list of [this.hotbar, this.inventory]) {
        for (let i = 0; i < list.length && rem > 0; i++) {
          const slot = list[i];
          if (slot && slot.id === id && slot.count < maxStack) {
            const add = Math.min(rem, maxStack - slot.count);
            slot.count += add;
            rem -= add;
          }
        }
      }
    }

    // 2. Place in empty hotbar / inventory slots
    for (const list of [this.hotbar, this.inventory]) {
      for (let i = 0; i < list.length && rem > 0; i++) {
        if (!list[i]) {
          const add = Math.min(rem, maxStack);
          list[i] = { id, count: add };
          rem -= add;
        }
      }
    }

    this.refreshHeldItemMeshes();
  }

  public showToast(msg: string): void {
    this.toastMessage = msg;
    if (this.toastTimeout !== null) {
      window.clearTimeout(this.toastTimeout);
    }
    this.toastTimeout = window.setTimeout(() => {
      this.toastMessage = null;
      this.emitHudState();
    }, 3400);
    this.emitHudState();
  }

  // ==================== INPUT EVENTS ====================

  private bindEvents(): void {
    window.addEventListener('resize', this.onResize);
    window.addEventListener('keydown', this.onKeyDown);
    window.addEventListener('keyup', this.onKeyUp);
    document.addEventListener('pointerlockchange', this.onPointerLockChange);

    const dom = this.renderer.domElement;
    dom.addEventListener('mousedown', this.onMouseDown);
    window.addEventListener('mouseup', this.onMouseUp);
    window.addEventListener('mousemove', this.onMouseMove);
    dom.addEventListener('touchstart', this.onTouchStart, { passive: false });
    dom.addEventListener('touchmove', this.onTouchMove, { passive: false });
    dom.addEventListener('touchend', this.onTouchEnd);
    dom.addEventListener('touchcancel', this.onTouchEnd);
    dom.addEventListener('wheel', this.onWheel, { passive: true });
    dom.addEventListener('contextmenu', this.onContextMenu);
  }

  private onResize = (): void => {
    if (this.disposed) return;
    const w = this.container.clientWidth || window.innerWidth;
    const h = this.container.clientHeight || window.innerHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.fpCamera.aspect = w / h;
    this.fpCamera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  };

  private onPointerLockChange = (): void => {
    this.pointerLocked = document.pointerLockElement === this.renderer.domElement;
    if (!this.pointerLocked) {
      this.mouseDownLeft = false;
    }
    this.emitHudState();
  };

  private onContextMenu = (e: MouseEvent): void => {
    e.preventDefault();
  };

  private onKeyDown = (e: KeyboardEvent): void => {
    const code = e.code;
    this.keys.add(code);

    if (!this.started) {
      if (code === 'Enter') this.startGame();
      return;
    }

    // Digit 1..9 hotbar selection
    if (code.startsWith('Digit')) {
      const num = parseInt(code.replace('Digit', ''), 10);
      if (num >= 1 && num <= 9) {
        this.selectHotbarSlot(num - 1);
        return;
      }
    }

    if (code === 'KeyE') {
      e.preventDefault();
      this.setModal(this.activeModal === 'inventory' ? 'none' : 'inventory');
      return;
    }

    if (code === 'KeyC') {
      e.preventDefault();
      this.setModal(this.activeModal === 'customizer' ? 'none' : 'customizer');
      return;
    }

    if (code === 'KeyH') {
      e.preventDefault();
      this.setModal(this.activeModal === 'help' ? 'none' : 'help');
      return;
    }

    if (code === 'Escape') {
      if (this.activeModal !== 'none') {
        this.setModal('none');
      }
      return;
    }

    if (this.activeModal !== 'none') return;

    if (code === 'KeyV') {
      this.cycleCameraMode();
    } else if (code === 'KeyG') {
      this.toggleGameMode();
    } else if (code === 'KeyN') {
      this.toggleDayNight();
    } else if (code === 'KeyF') {
      this.openNearbyNpcDialog();
    } else if (code === 'KeyR') {
      this.handleRightClickAction();
    }
  };

  private onKeyUp = (e: KeyboardEvent): void => {
    this.keys.delete(e.code);
  };

  private onWheel = (e: WheelEvent): void => {
    if (!this.started || this.activeModal !== 'none') return;
    const dir = e.deltaY > 0 ? 1 : -1;
    const next = (this.hotbarIndex + dir + 9) % 9;
    this.selectHotbarSlot(next);
  };

  private onMouseDown = (e: MouseEvent): void => {
    if (!this.started || this.activeModal !== 'none') return;

    if (!this.pointerLocked) {
      this.requestCanvasPointerLock();
    }

    if (e.button === 0) {
      this.draggingLook = true;
      this.lastMouseX = e.clientX;
      this.lastMouseY = e.clientY;
      this.playerSwingAnim = 1;

      // Check entity attack / TNT ignite first
      if (this.tryAttackOrInteractEntity(false)) {
        return;
      }
      if (this.currentRayHit && this.currentRayHit.blockId === BLOCK_IDS.TNT) {
        this.igniteTntAt(
          this.currentRayHit.bx,
          this.currentRayHit.by,
          this.currentRayHit.bz
        );
        return;
      }

      if (this.gameMode === 'creative' && this.currentRayHit) {
        this.breakVoxelBlock(
          this.currentRayHit.bx,
          this.currentRayHit.by,
          this.currentRayHit.bz,
          this.currentRayHit.blockId
        );
      } else {
        this.mouseDownLeft = true;
      }
    } else if (e.button === 2) {
      this.handleRightClickAction();
    }
  };

  private onMouseUp = (e: MouseEvent): void => {
    if (e.button === 0) {
      this.mouseDownLeft = false;
      this.draggingLook = false;
      this.miningElapsed = 0;
    }
  };

  private onMouseMove = (e: MouseEvent): void => {
    if (!this.started || this.activeModal !== 'none') return;
    const sens = 0.0024;

    if (this.pointerLocked) {
      this.rotateCameraBy(e.movementX * sens, e.movementY * sens);
    } else if (this.draggingLook) {
      const dx = e.clientX - this.lastMouseX;
      const dy = e.clientY - this.lastMouseY;
      this.lastMouseX = e.clientX;
      this.lastMouseY = e.clientY;
      if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
        this.rotateCameraBy(dx * sens * 1.4, dy * sens * 1.4);
      }
    }
  };

  private onTouchStart = (e: TouchEvent): void => {
    if (!this.started || this.activeModal !== 'none') return;
    if (this.lookTouchId === null && e.changedTouches.length > 0) {
      const t = e.changedTouches[0];
      this.lookTouchId = t.identifier;
      this.lastTouchX = t.clientX;
      this.lastTouchY = t.clientY;
    }
  };

  private onTouchMove = (e: TouchEvent): void => {
    if (!this.started || this.activeModal !== 'none') return;
    for (let i = 0; i < e.changedTouches.length; i++) {
      const t = e.changedTouches[i];
      if (t.identifier === this.lookTouchId) {
        e.preventDefault();
        const dx = t.clientX - this.lastTouchX;
        const dy = t.clientY - this.lastTouchY;
        this.lastTouchX = t.clientX;
        this.lastTouchY = t.clientY;
        const sens = 0.0052;
        this.rotateCameraBy(dx * sens, dy * sens);
        break;
      }
    }
  };

  private onTouchEnd = (e: TouchEvent): void => {
    for (let i = 0; i < e.changedTouches.length; i++) {
      if (e.changedTouches[i].identifier === this.lookTouchId) {
        this.lookTouchId = null;
        break;
      }
    }
  };

  public openNearbyNpcDialog(): void {
    const npc = this.npcs.find((n) => n.id === this.nearbyNpcId);
    if (!npc || npc.preset.isHostile) return;
    this.activeDialogNpcId = npc.id;
    this.setModal('npc_dialog');
    soundFX.playGreetingChime();
  }

  private tryAttackOrInteractEntity(allowTalk: boolean): boolean {
    const eye = this.getPlayerEyePos();
    const lookDir = this.getPlayerLookDir();

    let bestNpc: NpcEntity | null = null;
    let bestDist = 4.2;

    for (const npc of this.npcs) {
      const center = npc.pos.clone().add(new THREE.Vector3(0, 1.0, 0));
      const toNpc = center.sub(eye);
      const dist = toNpc.length();
      if (dist > bestDist) continue;
      const dot = toNpc.normalize().dot(lookDir);
      if (dot > 0.88) {
        bestDist = dist;
        bestNpc = npc;
      }
    }

    if (!bestNpc) return false;

    if (bestNpc.preset.isHostile) {
      const held = this.hotbar[this.hotbarIndex];
      const dmg = held ? getItemMeta(held.id).attackDamage ?? 3 : 3;
      this.damageNpc(bestNpc, dmg, lookDir);
      soundFX.playSwordSwing();
      return true;
    }

    if (allowTalk) {
      this.activeDialogNpcId = bestNpc.id;
      this.setModal('npc_dialog');
      soundFX.playGreetingChime();
      return true;
    }

    return false;
  }

  private handleRightClickAction(): void {
    // 1. Check if aiming directly at a friendly Korean NPC -> Talk!
    if (this.tryAttackOrInteractEntity(true)) {
      return;
    }

    const slot = this.hotbar[this.hotbarIndex];

    // 2. Check if aiming at Crafting Table -> Open Crafting Modal!
    if (this.currentRayHit && this.currentRayHit.blockId === BLOCK_IDS.CRAFTING_TABLE) {
      this.setModal('inventory');
      return;
    }

    if (!slot) return;
    const meta = getItemMeta(slot.id);

    // 3. Eat Korean Food (Kimbap / Tteokbokki)!
    if (meta.category === 'food') {
      if (this.health < this.maxHealth || this.hunger < this.maxHunger || this.gameMode === 'creative') {
        this.health = Math.min(this.maxHealth, this.health + (meta.healAmount ?? 4));
        this.hunger = Math.min(this.maxHunger, this.hunger + (meta.hungerAmount ?? 5));
        if (this.gameMode !== 'creative') {
          slot.count -= 1;
          if (slot.count <= 0) this.hotbar[this.hotbarIndex] = null;
          this.refreshHeldItemMeshes();
        }
        this.playerSwingAnim = 1;
        soundFX.playEat();
        this.showToast(`نوش جان! ${meta.nameFa} (${meta.nameKo}) سلامت و انرژی را بازیابی کرد ❤️`);
        this.emitHudState();
      } else {
        this.showToast('سلامتی و سیری شما کامل است!');
      }
      return;
    }

    // 4. Place Block on targeted voxel face!
    if (meta.isBlock && typeof slot.id === 'number' && this.currentRayHit) {
      const px = this.currentRayHit.bx + this.currentRayHit.nx;
      const py = this.currentRayHit.by + this.currentRayHit.ny;
      const pz = this.currentRayHit.bz + this.currentRayHit.nz;

      if (!this.world.inBounds(px, py, pz)) return;

      // Ensure placed block doesn't overlap player AABB (radius 0.3, height 1.78)
      const overlapsPlayer =
        px + 1 > this.playerPos.x - 0.28 &&
        px < this.playerPos.x + 0.28 &&
        pz + 1 > this.playerPos.z - 0.28 &&
        pz < this.playerPos.z + 0.28 &&
        py + 1 > this.playerPos.y + 0.02 &&
        py < this.playerPos.y + 1.76;

      if (overlapsPlayer) return;

      this.world.setBlock(px, py, pz, slot.id as BlockId);
      this.blocksPlaced++;
      this.playerSwingAnim = 1;
      soundFX.playPlace();

      if (this.gameMode !== 'creative') {
        slot.count -= 1;
        if (slot.count <= 0) this.hotbar[this.hotbarIndex] = null;
        this.refreshHeldItemMeshes();
      }
      this.emitHudState();
    }
  }

  private breakVoxelBlock(bx: number, by: number, bz: number, blockId: BlockId): void {
    if (by <= 0) return;
    this.world.setBlock(bx, by, bz, BLOCK_IDS.AIR);
    this.blocksMined++;
    soundFX.playBreak();
    this.spawnBlockParticles(bx + 0.5, by + 0.5, bz + 0.5, blockId, 14);

    if (this.gameMode !== 'creative') {
      let dropId: InventoryItemId = blockId;
      if (blockId === BLOCK_IDS.STONE) dropId = BLOCK_IDS.COBBLESTONE;
      else if (blockId === BLOCK_IDS.COAL_ORE) dropId = 'coal';
      else if (blockId === BLOCK_IDS.IRON_ORE) dropId = 'iron_ingot';
      else if (blockId === BLOCK_IDS.GOLD_ORE) dropId = 'gold_ingot';
      else if (blockId === BLOCK_IDS.DIAMOND_ORE) dropId = 'diamond';

      this.spawnPickup(dropId, 1, new THREE.Vector3(bx + 0.5, by + 0.5, bz + 0.5));
    }

    this.miningElapsed = 0;
    this.emitHudState();
  }

  private igniteTntAt(bx: number, by: number, bz: number): void {
    this.world.setBlock(bx, by, bz, BLOCK_IDS.AIR);
    const mats = this.texSys.getSingleBlockMaterials(BLOCK_IDS.TNT);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.98, 0.98, 0.98), mats);
    const pos = new THREE.Vector3(bx + 0.5, by + 0.5, bz + 0.5);
    mesh.position.copy(pos);
    this.scene.add(mesh);

    this.primedTnts.push({
      mesh,
      pos,
      vel: new THREE.Vector3((Math.random() - 0.5) * 2, 4.2, (Math.random() - 0.5) * 2),
      fuse: 2.3,
    });
    soundFX.playPlace();
    this.showToast('بلوک TNT روشن شد! فاصله بگیر! 💥');
  }

  private explodeAt(center: THREE.Vector3, radius: number): void {
    soundFX.playExplosion();
    this.spawnBlockParticles(center.x, center.y, center.z, BLOCK_IDS.TNT, 36);

    const cx = Math.floor(center.x);
    const cy = Math.floor(center.y);
    const cz = Math.floor(center.z);
    const r = Math.ceil(radius);

    for (let dy = -r; dy <= r; dy++) {
      for (let dz = -r; dz <= r; dz++) {
        for (let dx = -r; dx <= r; dx++) {
          if (dx * dx + dy * dy + dz * dz > radius * radius) continue;
          const bx = cx + dx;
          const by = cy + dy;
          const bz = cz + dz;
          if (by <= 1 || !this.world.inBounds(bx, by, bz)) continue;
          const b = this.world.getBlock(bx, by, bz);
          if (b !== BLOCK_IDS.AIR && b !== BLOCK_IDS.WATER) {
            this.world.setBlock(bx, by, bz, BLOCK_IDS.AIR);
            if (Math.random() < 0.25 && this.gameMode !== 'creative') {
              this.spawnPickup(b, 1, new THREE.Vector3(bx + 0.5, by + 0.5, bz + 0.5));
            }
          }
        }
      }
    }

    // Damage nearby Dokkaebi
    for (const npc of [...this.npcs]) {
      const d = npc.pos.distanceTo(center);
      if (d < radius + 2 && npc.preset.isHostile) {
        this.damageNpc(npc, 18, npc.pos.clone().sub(center).normalize());
      }
    }
  }

  private spawnPickup(itemId: InventoryItemId, count: number, pos: THREE.Vector3): void {
    const mesh =
      buildHeldItemMesh(itemId, (b) => this.texSys.getSingleBlockMaterials(b)) ??
      new THREE.Mesh(
        new THREE.BoxGeometry(0.25, 0.25, 0.25),
        new THREE.MeshLambertMaterial({ color: 0x3be8e0 })
      );
    mesh.position.copy(pos);
    this.scene.add(mesh);

    this.pickups.push({
      itemId,
      count,
      mesh,
      pos: pos.clone(),
      vel: new THREE.Vector3((Math.random() - 0.5) * 2.2, 3.4, (Math.random() - 0.5) * 2.2),
      age: 0,
    });
  }

  private spawnBlockParticles(
    x: number,
    y: number,
    z: number,
    blockId: BlockId,
    count: number
  ): void {
    const colorMap: Partial<Record<BlockId, number>> = {
      [BLOCK_IDS.GRASS]: 0x64b647,
      [BLOCK_IDS.DIRT]: 0x866042,
      [BLOCK_IDS.STONE]: 0x83878d,
      [BLOCK_IDS.COBBLESTONE]: 0x7d8188,
      [BLOCK_IDS.OAK_LOG]: 0x6b4d31,
      [BLOCK_IDS.OAK_PLANKS]: 0xba8e58,
      [BLOCK_IDS.CHERRY_LEAVES]: 0xffa8c4,
      [BLOCK_IDS.OAK_LEAVES]: 0x428a36,
      [BLOCK_IDS.HANOK_TILE]: 0x354156,
      [BLOCK_IDS.HANJI_WALL]: 0xfbf2df,
      [BLOCK_IDS.RED_PILLAR]: 0xb5282f,
      [BLOCK_IDS.LANTERN]: 0xffbf52,
      [BLOCK_IDS.DIAMOND_ORE]: 0x32e6df,
      [BLOCK_IDS.GOLD_ORE]: 0xf5c438,
      [BLOCK_IDS.TNT]: 0xdc352b,
    };
    const col = colorMap[blockId] ?? 0x9aa0a8;
    const geo = new THREE.BoxGeometry(0.13, 0.13, 0.13);
    const mat = new THREE.MeshLambertMaterial({ color: col });

    for (let i = 0; i < count; i++) {
      const m = new THREE.Mesh(geo, mat);
      m.position.set(
        x + (Math.random() - 0.5) * 0.5,
        y + (Math.random() - 0.5) * 0.5,
        z + (Math.random() - 0.5) * 0.5
      );
      this.scene.add(m);
      this.particles.push({
        mesh: m,
        vel: new THREE.Vector3(
          (Math.random() - 0.5) * 4.5,
          1.5 + Math.random() * 4.2,
          (Math.random() - 0.5) * 4.5
        ),
        life: 0,
        maxLife: 0.45 + Math.random() * 0.35,
        gravity: 13,
      });
    }
  }

  private damageNpc(npc: NpcEntity, amount: number, knockDir: THREE.Vector3): void {
    npc.hp -= amount;
    npc.hurtFlash = 0.25;
    npc.vel.x += knockDir.x * 5.2;
    npc.vel.z += knockDir.z * 5.2;
    npc.vel.y = 4.0;
    this.spawnBlockParticles(npc.pos.x, npc.pos.y + 1.1, npc.pos.z, BLOCK_IDS.RED_PILLAR, 8);

    if (npc.hp <= 0) {
      this.scene.remove(npc.rig.root);
      npc.rig.dispose();
      this.npcs = this.npcs.filter((n) => n.id !== npc.id);
      if (npc.preset.isHostile) {
        this.dokkaebiDefeated++;
        const reward: InventoryItemId = Math.random() > 0.45 ? 'diamond' : 'gold_ingot';
        this.spawnPickup(reward, 1, npc.pos.clone().add(new THREE.Vector3(0, 0.7, 0)));
        this.showToast('جنگجوی دوکه‌بی شکست خورد! غنیمت درخشان روی زمین افتاد ✨');
      }
      this.emitHudState();
    }
  }

  // ==================== MAIN SIMULATION LOOP ====================

  private loop = (now: number): void => {
    if (this.disposed) return;
    this.rafId = requestAnimationFrame(this.loop);

    const rawDt = (now - this.lastFrameTime) / 1000;
    this.lastFrameTime = now;
    const dt = Math.min(0.05, Math.max(0.001, rawDt));
    this.elapsedTotal += dt;

    // FPS counter
    this.fpsFrames++;
    this.fpsTimer += dt;
    if (this.fpsTimer >= 0.5) {
      this.fps = Math.round(this.fpsFrames / this.fpsTimer);
      this.fpsFrames = 0;
      this.fpsTimer = 0;
    }

    this.updateDayNightCycle(dt);
    this.updateCherryPetals(dt);

    if (this.started) {
      this.updatePlayer(dt);
      this.updateVoxelMining(dt);
    } else {
      this.updateTitleScreenCamera(dt);
    }

    this.updateNpcs(dt);
    this.updatePickups(dt);
    this.updatePrimedTnts(dt);
    this.updateParticles(dt);

    this.renderFrame();

    this.hudEmitTimer += dt;
    if (this.hudEmitTimer >= 0.14) {
      this.hudEmitTimer = 0;
      this.emitHudState();
    }
  };

  private updateTitleScreenCamera(_dt: number): void {
    // Cinematic gentle orbit around the Korean Hanok Plaza & Player Character!
    const angle = this.elapsedTotal * 0.22;
    const cx = 48.5;
    const cz = 46.5;
    this.camera.position.set(
      cx + Math.sin(angle) * 14.5,
      23.2 + Math.sin(this.elapsedTotal * 0.5) * 1.1,
      cz + Math.cos(angle) * 14.5
    );
    this.camera.lookAt(cx, 18.8, cz - 3);

    this.playerRig.root.visible = true;
    this.playerRig.root.position.copy(this.playerPos);
    this.playerRig.bodyGroup.rotation.y = this.elapsedTotal * 0.6;
    this.playerRig.animateWalk(0.25, this.elapsedTotal, 0);
  }

  private getPlayerEyePos(): THREE.Vector3 {
    return new THREE.Vector3(this.playerPos.x, this.playerPos.y + 1.62, this.playerPos.z);
  }

  private getPlayerLookDir(): THREE.Vector3 {
    const dir = new THREE.Vector3(0, 0, -1);
    const euler = new THREE.Euler(this.playerPitch, this.playerYaw, 0, 'YXZ');
    dir.applyEuler(euler);
    return dir.normalize();
  }

  private updatePlayer(dt: number): void {
    // Keyboard camera rotation fallback (Q / E / Arrow Keys)
    if (this.activeModal === 'none') {
      const turnSpeed = 2.0 * dt;
      if (this.keys.has('ArrowLeft') || this.keys.has('KeyQ')) {
        this.rotateCameraBy(-turnSpeed, 0);
      }
      if (this.keys.has('ArrowRight')) {
        this.rotateCameraBy(turnSpeed, 0);
      }
      if (this.keys.has('ArrowUp')) {
        this.rotateCameraBy(0, -turnSpeed * 0.7);
      }
      if (this.keys.has('ArrowDown')) {
        this.rotateCameraBy(0, turnSpeed * 0.7);
      }
    }

    // Movement vector
    let forward = 0;
    let strafe = 0;
    if (this.activeModal === 'none') {
      if (this.keys.has('KeyW')) forward += 1;
      if (this.keys.has('KeyS')) forward -= 1;
      if (this.keys.has('KeyD')) strafe += 1;
      if (this.keys.has('KeyA')) strafe -= 1;
      forward += this.mobileMoveZ;
      strafe += this.mobileMoveX;
    }

    const sprinting = this.keys.has('ShiftLeft') || this.keys.has('ShiftRight');
    const baseSpeed = this.gameMode === 'creative' ? 6.8 : sprinting ? 6.4 : 4.6;

    const sinY = Math.sin(this.playerYaw);
    const cosY = Math.cos(this.playerYaw);

    let moveX = -sinY * forward + cosY * strafe;
    let moveZ = -cosY * forward - sinY * strafe;
    const moveLen = Math.hypot(moveX, moveZ);
    if (moveLen > 1) {
      moveX /= moveLen;
      moveZ /= moveLen;
    }

    this.playerVel.x = moveX * baseSpeed;
    this.playerVel.z = moveZ * baseSpeed;

    // Check if swimming in water
    const footBlock = this.world.getBlock(
      Math.floor(this.playerPos.x),
      Math.floor(this.playerPos.y + 0.5),
      Math.floor(this.playerPos.z)
    );
    const inWater = footBlock === BLOCK_IDS.WATER;

    const wantJump =
      this.activeModal === 'none' && (this.keys.has('Space') || this.mobileJumping);

    if (inWater) {
      this.playerVel.y -= 8.5 * dt;
      this.playerVel.y = Math.max(-2.8, this.playerVel.y);
      if (wantJump) {
        this.playerVel.y = 4.2;
      }
    } else {
      this.playerVel.y -= 23.5 * dt;
      this.playerVel.y = Math.max(-32, this.playerVel.y);
      if (wantJump && this.onGround) {
        this.playerVel.y = 8.15;
        this.onGround = false;
      }
    }

    this.moveEntityWithVoxelAABB(this.playerPos, this.playerVel, dt, 0.3, 1.78, true);

    // Hunger & passive health regen in Survival
    if (this.gameMode === 'survival') {
      this.hungerTick += dt * (moveLen > 0.2 ? 1.2 : 0.25);
      if (this.hungerTick >= 18) {
        this.hungerTick = 0;
        this.hunger = Math.max(2, this.hunger - 1);
      }
      if (this.hunger >= 16 && this.health < this.maxHealth) {
        this.health = Math.min(this.maxHealth, this.health + dt * 0.45);
      }
    }

    // Player Blink & Rig Animation
    this.playerBlinkTimer -= dt;
    if (this.playerBlinkTimer <= 0) {
      if (this.playerIsBlinking) {
        this.playerIsBlinking = false;
        this.playerBlinkTimer = 2.4 + Math.random() * 3.4;
      } else {
        this.playerIsBlinking = true;
        this.playerBlinkTimer = 0.14;
      }
      this.playerRig.setBlinking(this.playerIsBlinking);
    }

    if (this.playerSwingAnim > 0) {
      this.playerSwingAnim = Math.max(0, this.playerSwingAnim - dt * 4.5);
    }

    const horizSpeed = Math.hypot(this.playerVel.x, this.playerVel.z) / 5.0;
    this.playerRig.root.position.copy(this.playerPos);
    // Rig forward is +Z, whereas camera yaw=0 looks toward -Z, so add Math.PI
    this.playerRig.bodyGroup.rotation.y = this.playerYaw + Math.PI;
    this.playerRig.headPivot.rotation.x = -this.playerPitch * 0.7;
    this.playerRig.animateWalk(horizSpeed, this.elapsedTotal, 1 - this.playerSwingAnim > 0.99 ? 0 : this.playerSwingAnim);

    this.playerRig.root.visible = this.cameraMode !== 'first_person';

    // Update Camera Position according to active CameraMode!
    const eye = this.getPlayerEyePos();
    const lookDir = this.getPlayerLookDir();

    if (this.cameraMode === 'first_person') {
      const bob = this.onGround && horizSpeed > 0.1 ? Math.sin(this.elapsedTotal * 11) * 0.038 * horizSpeed : 0;
      this.camera.position.set(eye.x, eye.y + bob, eye.z);
      this.camera.rotation.order = 'YXZ';
      this.camera.rotation.y = this.playerYaw;
      this.camera.rotation.x = this.playerPitch;
      this.camera.rotation.z = 0;

      // Animate 1st-person arm bob & swing
      const swingSin = this.playerSwingAnim > 0 ? Math.sin(this.playerSwingAnim * Math.PI) : 0;
      this.fpArmGroup.position.set(
        0.52 - swingSin * 0.14,
        -0.46 + Math.abs(bob) * 1.4 - swingSin * 0.1,
        -0.72 - swingSin * 0.16
      );
      this.fpArmGroup.rotation.set(-swingSin * 0.75, swingSin * 0.35, 0);
    } else if (this.cameraMode === 'third_back') {
      const backDir = lookDir.clone().negate().add(new THREE.Vector3(0, 0.12, 0)).normalize();
      const camRay = this.world.raycast(eye, backDir, 3.6);
      const safeDist = camRay ? Math.max(0.65, camRay.distance - 0.35) : 3.6;
      const camBack = eye.clone().addScaledVector(backDir, safeDist);
      this.camera.position.copy(camBack);
      this.camera.lookAt(eye.clone().addScaledVector(lookDir, 4));
    } else {
      // third_front (Selfie view of your Korean character face!)
      const forwardHoriz = new THREE.Vector3(-Math.sin(this.playerYaw), 0.12, -Math.cos(this.playerYaw)).normalize();
      const camRay = this.world.raycast(eye, forwardHoriz, 2.55);
      const safeDist = camRay ? Math.max(0.65, camRay.distance - 0.35) : 2.55;
      const camFront = eye.clone().addScaledVector(forwardHoriz, safeDist);
      this.camera.position.copy(camFront);
      this.camera.lookAt(this.playerPos.x, this.playerPos.y + 1.52, this.playerPos.z);
    }

    // Update Block Raycast Highlight
    this.currentRayHit = this.world.raycast(eye, lookDir, 6.2);
    if (this.currentRayHit && this.activeModal === 'none') {
      this.highlightBox.visible = true;
      this.highlightBox.position.set(
        this.currentRayHit.bx + 0.5,
        this.currentRayHit.by + 0.5,
        this.currentRayHit.bz + 0.5
      );
    } else {
      this.highlightBox.visible = false;
    }
  }

  private updateVoxelMining(dt: number): void {
    if (!this.mouseDownLeft || !this.currentRayHit || this.activeModal !== 'none') {
      this.miningElapsed = 0;
      this.crackBox.visible = false;
      return;
    }

    const hit = this.currentRayHit;
    const key = `${hit.bx}_${hit.by}_${hit.bz}`;
    if (key !== this.miningBlockKey) {
      this.miningBlockKey = key;
      this.miningElapsed = 0;
    }

    const blockMeta = getItemMeta(hit.blockId);
    let hardness = blockMeta.hardness ?? 0.6;
    const held = this.hotbar[this.hotbarIndex];
    if (held) {
      if (held.id === 'diamond_pickaxe' && blockMeta.preferredTool === 'pickaxe') {
        hardness *= 0.28;
      } else if (held.id === 'iron_axe' && blockMeta.preferredTool === 'axe') {
        hardness *= 0.34;
      }
    }
    this.miningDuration = Math.max(0.14, hardness);
    this.miningElapsed += dt;

    // Continuous arm swing & dig sound
    if (this.playerSwingAnim <= 0.05) {
      this.playerSwingAnim = 1;
    }
    this.digSoundTimer += dt;
    if (this.digSoundTimer >= 0.22) {
      this.digSoundTimer = 0;
      soundFX.playDig();
    }

    this.crackBox.visible = true;
    this.crackBox.position.set(hit.bx + 0.5, hit.by + 0.5, hit.bz + 0.5);
    const mat = this.crackBox.material as THREE.MeshBasicMaterial;
    mat.opacity = Math.min(0.75, (this.miningElapsed / this.miningDuration) * 0.8);

    if (this.miningElapsed >= this.miningDuration) {
      this.crackBox.visible = false;
      this.breakVoxelBlock(hit.bx, hit.by, hit.bz, hit.blockId);
    }
  }

  private moveEntityWithVoxelAABB(
    pos: THREE.Vector3,
    vel: THREE.Vector3,
    dt: number,
    radius: number,
    height: number,
    isPlayer: boolean
  ): boolean {
    let grounded = false;

    const collidesAt = (nx: number, ny: number, nz: number): boolean => {
      const minX = Math.floor(nx - radius);
      const maxX = Math.floor(nx + radius);
      const minY = Math.floor(ny);
      const maxY = Math.floor(ny + height);
      const minZ = Math.floor(nz - radius);
      const maxZ = Math.floor(nz + radius);

      for (let y = minY; y <= maxY; y++) {
        for (let z = minZ; z <= maxZ; z++) {
          for (let x = minX; x <= maxX; x++) {
            if (this.world.isSolid(x, y, z)) return true;
          }
        }
      }
      return false;
    };

    // Y axis
    const nextY = pos.y + vel.y * dt;
    if (!collidesAt(pos.x, nextY, pos.z)) {
      pos.y = nextY;
    } else {
      if (vel.y < 0) {
        pos.y = Math.floor(nextY) + 1.0001;
        grounded = true;
      }
      vel.y = 0;
    }

    // X axis
    const nextX = pos.x + vel.x * dt;
    if (!collidesAt(nextX, pos.y + 0.02, pos.z)) {
      pos.x = nextX;
    } else if (!isPlayer && grounded && !collidesAt(nextX, pos.y + 1.05, pos.z)) {
      // Auto-step 1 block for smooth NPC village navigation!
      pos.y += 1.02;
      pos.x = nextX;
    } else {
      vel.x = 0;
    }

    // Z axis
    const nextZ = pos.z + vel.z * dt;
    if (!collidesAt(pos.x, pos.y + 0.02, nextZ)) {
      pos.z = nextZ;
    } else if (!isPlayer && grounded && !collidesAt(pos.x, pos.y + 1.05, nextZ)) {
      pos.y += 1.02;
      pos.z = nextZ;
    } else {
      vel.z = 0;
    }

    if (isPlayer) {
      this.onGround = grounded;
    }
    return grounded;
  }

  private updateNpcs(dt: number): void {
    // Night-time Dokkaebi spawning in Survival mode (gentle & fun, max 2 natural at night)
    const isNight = this.timeOfDay > 0.58 && this.timeOfDay < 0.92;
    if (this.started && isNight && this.gameMode === 'survival') {
      this.dokkaebiSpawnTimer -= dt;
      const hostileCount = this.npcs.filter((n) => n.preset.isHostile).length;
      if (this.dokkaebiSpawnTimer <= 0 && hostileCount < 2) {
        this.dokkaebiSpawnTimer = 22;
        const dokkaebiPreset = KOREAN_CHARACTER_PRESETS.find((p) => p.id === 'dokkaebi');
        if (dokkaebiPreset) {
          const ang = Math.random() * Math.PI * 2;
          const sx = Math.max(10, Math.min(WORLD_WIDTH - 10, this.playerPos.x + Math.cos(ang) * 15));
          const sz = Math.max(10, Math.min(WORLD_DEPTH - 10, this.playerPos.z + Math.sin(ang) * 15));
          this.spawnNpcFromPreset(dokkaebiPreset, sx, sz, 0, 'dokkaebi_club');
        }
      }
    }

    let closestFriendly: NpcEntity | null = null;
    let closestDist = 4.2;

    for (const npc of this.npcs) {
      // Natural eye blinking on EVERY Korean character!
      npc.blinkTimer -= dt;
      if (npc.blinkTimer <= 0) {
        npc.isBlinking = !npc.isBlinking;
        npc.blinkTimer = npc.isBlinking ? 0.14 : 2.2 + Math.random() * 3.8;
        npc.rig.setBlinking(npc.isBlinking);
      }

      if (npc.hurtFlash > 0) {
        npc.hurtFlash = Math.max(0, npc.hurtFlash - dt);
      }
      if (npc.attackCooldown > 0) {
        npc.attackCooldown = Math.max(0, npc.attackCooldown - dt);
      }
      if (npc.swingAnim > 0) {
        npc.swingAnim = Math.max(0, npc.swingAnim - dt * 4);
      }

      const distToPlayer = npc.pos.distanceTo(this.playerPos);

      if (!npc.preset.isHostile && distToPlayer < closestDist) {
        closestDist = distToPlayer;
        closestFriendly = npc;
      }

      // AI Behavior
      if (npc.preset.isHostile) {
        // Hostile Dokkaebi chases player!
        const dx = this.playerPos.x - npc.pos.x;
        const dz = this.playerPos.z - npc.pos.z;
        npc.targetYaw = Math.atan2(dx, dz);
        if (distToPlayer > 1.55 && distToPlayer < 26) {
          npc.vel.x = Math.sin(npc.targetYaw) * 2.85;
          npc.vel.z = Math.cos(npc.targetYaw) * 2.85;
        } else {
          npc.vel.x *= 0.8;
          npc.vel.z *= 0.8;
        }
        if (distToPlayer <= 1.85 && npc.attackCooldown <= 0 && this.started && this.gameMode === 'survival') {
          npc.attackCooldown = 1.4;
          npc.swingAnim = 1;
          this.health = Math.max(1, this.health - 2);
          soundFX.playSwordSwing();
          this.showToast('دوکه‌بی ضربه زد! با شمشیر چوسان دفاع کن یا کیمباب بخور!');
        }
      } else {
        // Friendly Korean Villager / Joseon Guard / Companion AI!
        const nearestHostile = this.npcs.find(
          (other) => other.preset.isHostile && other.pos.distanceTo(npc.pos) < 12
        );

        if ((npc.preset.id === 'jihoon' || npc.isFollowing) && nearestHostile) {
          // Guard Ji-hoon & Companions heroically fight Dokkaebi!
          const dx = nearestHostile.pos.x - npc.pos.x;
          const dz = nearestHostile.pos.z - npc.pos.z;
          const d = Math.hypot(dx, dz);
          npc.targetYaw = Math.atan2(dx, dz);
          if (d > 1.6) {
            npc.vel.x = Math.sin(npc.targetYaw) * 3.4;
            npc.vel.z = Math.cos(npc.targetYaw) * 3.4;
          } else if (npc.attackCooldown <= 0) {
            npc.attackCooldown = 0.95;
            npc.swingAnim = 1;
            this.damageNpc(
              nearestHostile,
              6,
              new THREE.Vector3(dx, 0, dz).normalize()
            );
          }
        } else if (npc.isFollowing) {
          // Companion follows player loyally!
          if (distToPlayer > 18) {
            const sy = this.world.getSurfaceY(this.playerPos.x + 1.5, this.playerPos.z + 1.5);
            npc.pos.set(this.playerPos.x + 1.5, sy + 0.1, this.playerPos.z + 1.5);
          } else if (distToPlayer > 2.8) {
            const dx = this.playerPos.x - npc.pos.x;
            const dz = this.playerPos.z - npc.pos.z;
            npc.targetYaw = Math.atan2(dx, dz);
            npc.vel.x = Math.sin(npc.targetYaw) * 3.8;
            npc.vel.z = Math.cos(npc.targetYaw) * 3.8;
          } else {
            npc.vel.x *= 0.75;
            npc.vel.z *= 0.75;
            npc.targetYaw = Math.atan2(
              this.playerPos.x - npc.pos.x,
              this.playerPos.z - npc.pos.z
            );
          }
        } else {
          // Peaceful village stroll; look warmly at player when nearby!
          npc.aiTimer -= dt;
          if (npc.aiTimer <= 0) {
            npc.aiTimer = 2.0 + Math.random() * 3.5;
            npc.moving = Math.random() > 0.45;
            // Gently bias wandering back toward the central plaza (48, 46)
            const distFromPlaza = Math.hypot(npc.pos.x - 48, npc.pos.z - 46);
            if (distFromPlaza > 22) {
              npc.targetYaw = Math.atan2(48 - npc.pos.x, 46 - npc.pos.z);
            } else {
              npc.targetYaw += (Math.random() - 0.5) * 2.2;
            }
          }

          if (distToPlayer < 5.2 && this.started) {
            npc.vel.x *= 0.75;
            npc.vel.z *= 0.75;
            const lookAtPlayerYaw = Math.atan2(
              this.playerPos.x - npc.pos.x,
              this.playerPos.z - npc.pos.z
            );
            npc.targetYaw = lookAtPlayerYaw;
          } else if (npc.moving) {
            const aheadX = Math.floor(npc.pos.x + Math.sin(npc.targetYaw) * 1.2);
            const aheadZ = Math.floor(npc.pos.z + Math.cos(npc.targetYaw) * 1.2);
            const aheadSurface = this.world.getSurfaceY(aheadX, aheadZ);
            if (aheadSurface <= WATER_LEVEL) {
              // Avoid walking into pond water
              npc.targetYaw += Math.PI * 0.8;
              npc.vel.x = 0;
              npc.vel.z = 0;
            } else {
              npc.vel.x = Math.sin(npc.targetYaw) * 1.55;
              npc.vel.z = Math.cos(npc.targetYaw) * 1.55;
            }
          } else {
            npc.vel.x *= 0.78;
            npc.vel.z *= 0.78;
          }
        }
      }

      // Gravity & Voxel collision for NPC
      npc.vel.y = Math.max(-28, npc.vel.y - 22 * dt);
      this.moveEntityWithVoxelAABB(npc.pos, npc.vel, dt, 0.28, 1.75, false);

      // Smooth yaw interpolation
      let diff = npc.targetYaw - npc.yaw;
      while (diff > Math.PI) diff -= Math.PI * 2;
      while (diff < -Math.PI) diff += Math.PI * 2;
      npc.yaw += diff * Math.min(1, dt * 7);

      const moveSpd = Math.hypot(npc.vel.x, npc.vel.z) / 3.0;
      npc.rig.root.position.copy(npc.pos);
      npc.rig.bodyGroup.rotation.y = npc.yaw;
      npc.rig.animateWalk(moveSpd, this.elapsedTotal + npc.pos.x, npc.swingAnim);
    }

    this.nearbyNpcId = closestFriendly ? closestFriendly.id : null;
  }

  private updatePickups(dt: number): void {
    for (let i = this.pickups.length - 1; i >= 0; i--) {
      const p = this.pickups[i];
      p.age += dt;
      p.vel.y = Math.max(-16, p.vel.y - 18 * dt);

      const nextY = p.pos.y + p.vel.y * dt;
      if (!this.world.isSolid(Math.floor(p.pos.x), Math.floor(nextY - 0.15), Math.floor(p.pos.z))) {
        p.pos.y = nextY;
      } else {
        p.vel.y = 0;
        p.vel.x *= 0.85;
        p.vel.z *= 0.85;
      }
      p.pos.x += p.vel.x * dt;
      p.pos.z += p.vel.z * dt;

      p.mesh.position.set(p.pos.x, p.pos.y + Math.sin(this.elapsedTotal * 4 + i) * 0.08, p.pos.z);
      p.mesh.rotation.y += dt * 2.4;

      // Magnetic pickup toward player
      const playerCenter = new THREE.Vector3(
        this.playerPos.x,
        this.playerPos.y + 0.9,
        this.playerPos.z
      );
      const dist = p.pos.distanceTo(playerCenter);
      if (p.age > 0.35 && dist < 2.5) {
        p.pos.lerp(playerCenter, dt * 11);
        if (dist < 0.85) {
          this.addItemToInventory(p.itemId, p.count);
          soundFX.playPickup();
          this.scene.remove(p.mesh);
          this.pickups.splice(i, 1);
          this.emitHudState();
          continue;
        }
      }

      if (p.age > 90) {
        this.scene.remove(p.mesh);
        this.pickups.splice(i, 1);
      }
    }
  }

  private updatePrimedTnts(dt: number): void {
    for (let i = this.primedTnts.length - 1; i >= 0; i--) {
      const t = this.primedTnts[i];
      t.fuse -= dt;
      t.vel.y -= 18 * dt;
      this.moveEntityWithVoxelAABB(t.pos, t.vel, dt, 0.45, 0.95, false);
      t.mesh.position.copy(t.pos);
      const pulse = 1 + Math.sin(t.fuse * 26) * 0.08;
      t.mesh.scale.setScalar(pulse);

      if (t.fuse <= 0) {
        this.scene.remove(t.mesh);
        this.primedTnts.splice(i, 1);
        this.explodeAt(t.pos, 3.3);
      }
    }
  }

  private updateParticles(dt: number): void {
    for (let i = this.particles.length - 1; i >= 0; i--) {
      const p = this.particles[i];
      p.life += dt;
      p.vel.y -= p.gravity * dt;
      p.mesh.position.addScaledVector(p.vel, dt);
      p.mesh.rotation.x += dt * 5;
      p.mesh.rotation.y += dt * 4;
      const scale = Math.max(0.01, 1 - p.life / p.maxLife);
      p.mesh.scale.setScalar(scale);

      if (p.life >= p.maxLife) {
        this.scene.remove(p.mesh);
        this.particles.splice(i, 1);
      }
    }
  }

  private updateCherryPetals(dt: number): void {
    if (!this.cherryPetals) return;
    const attr = this.cherryPetals.geometry.getAttribute('position') as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    for (let i = 0; i < arr.length; i += 3) {
      arr[i] += Math.sin(this.elapsedTotal * 0.8 + i) * 0.45 * dt;
      arr[i + 1] -= 0.85 * dt;
      arr[i + 2] += Math.cos(this.elapsedTotal * 0.7 + i) * 0.35 * dt;
      if (arr[i + 1] < 14.5) {
        arr[i + 1] = 31 + Math.random() * 5;
      }
    }
    attr.needsUpdate = true;
  }

  private updateDayNightCycle(dt: number): void {
    // 1 full cycle = ~320 seconds
    this.timeOfDay += dt / 320;
    if (this.timeOfDay >= 1) {
      this.timeOfDay -= 1;
      this.dayCount++;
    }

    const sunAngle = this.timeOfDay * Math.PI * 2;
    const sunElev = Math.sin(sunAngle); // >0 day, <0 night

    const centerX = 48;
    const centerZ = 48;
    const orbitR = 115;

    this.sunMesh.position.set(
      centerX + Math.cos(sunAngle) * orbitR,
      20 + Math.sin(sunAngle) * orbitR,
      centerZ - 25
    );
    this.moonMesh.position.set(
      centerX - Math.cos(sunAngle) * orbitR,
      20 - Math.sin(sunAngle) * orbitR,
      centerZ - 25
    );

    this.sunLight.position.copy(this.sunMesh.position);

    const daySky = new THREE.Color(0x80c7f9);
    const sunsetSky = new THREE.Color(0xeb9872);
    const nightSky = new THREE.Color(0x11192e);

    let skyColor: THREE.Color;
    if (sunElev > 0.22) {
      skyColor = daySky;
      this.sunLight.intensity = 0.92;
      this.ambientLight.intensity = 0.64;
    } else if (sunElev > -0.14) {
      const t = (sunElev + 0.14) / 0.36;
      skyColor = nightSky.clone().lerp(sunsetSky, Math.sin(t * Math.PI)).lerp(daySky, t);
      this.sunLight.intensity = 0.25 + t * 0.67;
      this.ambientLight.intensity = 0.36 + t * 0.28;
    } else {
      skyColor = nightSky;
      this.sunLight.intensity = 0.18;
      this.ambientLight.intensity = 0.38;
    }

    (this.scene.background as THREE.Color).copy(skyColor);
    if (this.scene.fog instanceof THREE.FogExp2) {
      this.scene.fog.color.copy(skyColor);
    }
  }

  private renderFrame(): void {
    this.renderer.clear();
    this.renderer.render(this.scene, this.camera);

    if (this.started && this.cameraMode === 'first_person') {
      this.renderer.clearDepth();
      this.renderer.render(this.fpScene, this.fpCamera);
    }
  }

  private toNpcSnapshot(npc: NpcEntity | undefined): NpcStatusSnapshot | null {
    if (!npc) return null;
    return {
      entityId: npc.id,
      preset: npc.preset,
      isFollowing: npc.isFollowing,
      hp: Math.ceil(npc.hp),
      maxHp: npc.maxHp,
    };
  }

  public emitHudState(): void {
    const isNight = this.timeOfDay > 0.56 && this.timeOfDay < 0.94;
    let timeLabelFa = 'روز بهاری ☀️';
    if (this.timeOfDay >= 0.46 && this.timeOfDay <= 0.56) timeLabelFa = 'غروب طلایی سئول 🌇';
    else if (isNight) timeLabelFa = 'شب فانوس‌ها 🏮';
    else if (this.timeOfDay >= 0.94 || this.timeOfDay < 0.08) timeLabelFa = 'طلوع صبحگاهی 🌸';

    const nearby = this.npcs.find((n) => n.id === this.nearbyNpcId);
    const dialogNpc = this.npcs.find((n) => n.id === this.activeDialogNpcId);

    this.onHudUpdate({
      started: this.started,
      activeModal: this.activeModal,
      health: Math.round(this.health),
      maxHealth: this.maxHealth,
      hunger: Math.round(this.hunger),
      maxHunger: this.maxHunger,
      hotbarIndex: this.hotbarIndex,
      hotbar: this.hotbar.map((s) => (s ? { ...s } : null)),
      inventory: this.inventory.map((s) => (s ? { ...s } : null)),
      cameraMode: this.cameraMode,
      gameMode: this.gameMode,
      timeLabelFa,
      isNight,
      dayCount: this.dayCount,
      coords: {
        x: Math.floor(this.playerPos.x),
        y: Math.floor(this.playerPos.y),
        z: Math.floor(this.playerPos.z),
      },
      fps: this.fps,
      playerNameFa: this.playerPreset.nameFa,
      playerNameKo: this.playerPreset.nameKo,
      playerFace: { ...this.playerFace },
      playerPortraitUrl: this.playerPortraitUrl,
      nearbyNpc: this.toNpcSnapshot(nearby),
      activeDialogNpc: this.toNpcSnapshot(dialogNpc),
      companionsCount: this.npcs.filter((n) => n.isFollowing).length,
      totalNpcsInWorld: this.npcs.filter((n) => !n.preset.isHostile).length,
      dokkaebiDefeated: this.dokkaebiDefeated,
      blocksMined: this.blocksMined,
      blocksPlaced: this.blocksPlaced,
      pointerLocked: this.pointerLocked,
      toastMessage: this.toastMessage,
      breakingProgress:
        this.miningDuration > 0
          ? Math.min(1, this.miningElapsed / this.miningDuration)
          : 0,
      targetBlockNameFa: this.currentRayHit
        ? getItemMeta(this.currentRayHit.blockId).nameFa
        : null,
    });
  }

  public getCraftingRecipes(): CraftingRecipe[] {
    return CRAFTING_RECIPES;
  }

  public getCreativeItems(): InventoryItemId[] {
    return ALL_CREATIVE_ITEMS;
  }

  public dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.rafId);
    window.removeEventListener('resize', this.onResize);
    window.removeEventListener('keydown', this.onKeyDown);
    window.removeEventListener('keyup', this.onKeyUp);
    document.removeEventListener('pointerlockchange', this.onPointerLockChange);
    window.removeEventListener('mouseup', this.onMouseUp);
    window.removeEventListener('mousemove', this.onMouseMove);
    this.renderer.dispose();
    if (this.renderer.domElement.parentNode === this.container) {
      this.container.removeChild(this.renderer.domElement);
    }
  }
}
