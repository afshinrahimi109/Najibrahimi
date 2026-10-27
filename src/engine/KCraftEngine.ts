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
  ControlStyle,
  CraftingRecipe,
  GameMode,
  HudState,
  InventoryItemId,
  InventorySlot,
  KoreanFaceConfig,
  LiveChatMessage,
  NpcStatusSnapshot,
  QuestProgress,
  RadarDot,
  TradeOffer,
  WorldBiomeId,
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
  portraitUrl: string;
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
  greetCooldown: number;
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

const ACCENT_PALETTE = [
  '#FF7EB6',
  '#4CE8E0',
  '#FFD166',
  '#7AE582',
  '#9B8CFF',
  '#FF9F68',
];

export class KCraftEngine {
  private readonly container: HTMLElement;
  private readonly onHudUpdate: (state: HudState) => void;

  public readonly texSys: BlockTextureSystem;
  public readonly world: VoxelWorld;
  public readonly presetPortraits: Record<string, string> = {};

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
  private playerYaw = Math.PI;
  private playerPitch = -0.06;
  private onGround = false;
  private isFlying = false;

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
  private worldBiome: WorldBiomeId = 'hanok_valley';
  private cameraMode: CameraMode = 'first_person';
  private gameMode: GameMode = 'survival';

  // Settings
  private controlStyle: ControlStyle = 'joystick';
  private lookSensitivity = 1.0;

  private health = 20;
  private maxHealth = 20;
  private hunger = 20;
  private maxHunger = 20;
  private hungerTick = 0;

  // RPG Progression & Quests
  private playerLevel = 1;
  private playerXp = 0;
  private goldCoins = 120;
  private socialInteractions = 0;
  private itemsCrafted = 0;
  private talkedNpcSet = new Set<string>();
  private quests: QuestProgress[] = [];

  // Live Animated Enter/Exit Chat Feed
  private liveChatFeed: LiveChatMessage[] = [];
  private villageChatterTimer = 9;

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
  private dokkaebiSpawnTimer = 14;

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

  // Mobile virtual controller state
  public mobileMoveX = 0;
  public mobileMoveZ = 0;
  public mobileJumping = false;
  public mobileFlyUp = false;
  public mobileFlyDown = false;
  public mobileSprinting = false;

  constructor(container: HTMLElement, onHudUpdate: (state: HudState) => void) {
    this.container = container;
    this.onHudUpdate = onHudUpdate;

    this.texSys = getBlockTextureSystem();
    this.world = new VoxelWorld(this.texSys);

    // Pre-render crisp Korean portraits for all character presets
    for (const p of KOREAN_CHARACTER_PRESETS) {
      this.presetPortraits[p.id] = renderCharacterPortraitDataUrl(p.face);
    }

    this.initQuests();
    this.initScene();
    this.initStarterInventory();
    this.initPlayerRig();
    this.spawnVillageKoreanCharacters();
    this.initCherryBlossomParticles();
    this.bindEvents();

    const spawnY = this.world.getSurfaceY(48, 51);
    this.playerPos.set(48.5, spawnY + 0.05, 51.5);
    this.playerPortraitUrl = renderCharacterPortraitDataUrl(this.playerFace);

    this.emitHudState();
    this.lastFrameTime = performance.now();
    this.loop(this.lastFrameTime);
  }

  private initQuests(): void {
    this.quests = [
      {
        id: 'q_mine',
        titleFa: 'کاوشگر معدن چوسان',
        descFa: '۱۰ بلوک سنگ، چوب یا سنگ‌معدن استخراج کن',
        category: 'mine',
        current: 0,
        target: 10,
        rewardXp: 80,
        rewardCoins: 100,
        rewardItemId: 'diamond',
        rewardItemCount: 3,
        claimed: false,
      },
      {
        id: 'q_build',
        titleFa: 'معمار عمارت هانوک',
        descFa: '۱۲ بلوک در دهکده کره‌ای یا شهر سئول قرار بده',
        category: 'build',
        current: 0,
        target: 12,
        rewardXp: 90,
        rewardCoins: 120,
        rewardItemId: BLOCK_IDS.NEON_CYAN,
        rewardItemCount: 16,
        claimed: false,
      },
      {
        id: 'q_social',
        titleFa: 'دوستی با اهالی کره‌ای',
        descFa: 'با ۲ نفر از شخصیت‌های کره‌ای گفت‌وگو یا معامله کن',
        category: 'social',
        current: 0,
        target: 2,
        rewardXp: 70,
        rewardCoins: 90,
        rewardItemId: 'bingsoo',
        rewardItemCount: 4,
        claimed: false,
      },
      {
        id: 'q_craft',
        titleFa: 'استاد کارگاه ساخت‌وساز',
        descFa: '۲ بار در بخش ساخت‌وساز آیتم یا بلوک بساز',
        category: 'craft',
        current: 0,
        target: 2,
        rewardXp: 85,
        rewardCoins: 110,
        rewardItemId: BLOCK_IDS.GOLD_BLOCK,
        rewardItemCount: 8,
        claimed: false,
      },
      {
        id: 'q_combat',
        titleFa: 'نگهبان افسانه دوکه‌بی',
        descFa: '۱ جنگجوی دوکه‌بی (도깨비) را شکست بده',
        category: 'combat',
        current: 0,
        target: 1,
        rewardXp: 150,
        rewardCoins: 200,
        rewardItemId: 'diamond',
        rewardItemCount: 5,
        claimed: false,
      },
    ];
  }

  private syncQuestProgress(): void {
    for (const q of this.quests) {
      const prevDone = q.current >= q.target;
      if (q.category === 'mine') q.current = Math.min(q.target, this.blocksMined);
      else if (q.category === 'build') q.current = Math.min(q.target, this.blocksPlaced);
      else if (q.category === 'social') q.current = Math.min(q.target, this.socialInteractions);
      else if (q.category === 'craft') q.current = Math.min(q.target, this.itemsCrafted);
      else if (q.category === 'combat') q.current = Math.min(q.target, this.dokkaebiDefeated);

      if (!prevDone && q.current >= q.target) {
        soundFX.playQuestComplete();
        this.pushLiveChat({
          senderFa: 'دفتر مأموریت سلطنتی',
          senderKo: '왕실 임무 완료',
          roleFa: 'پاداش آماده دریافت!',
          portraitUrl: this.playerPortraitUrl,
          text: `آفرین! مأموریت «${q.titleFa}» کامل شد! جایزه‌ات را از صفحه مأموریت‌ها بگیر 🎁`,
          accentColor: '#FFD166',
          durationMs: 5200,
        });
      }
    }
  }

  public claimQuestReward(questId: string): void {
    const q = this.quests.find((item) => item.id === questId);
    if (!q || q.claimed || q.current < q.target) return;
    q.claimed = true;
    this.goldCoins += q.rewardCoins;
    this.gainXp(q.rewardXp);
    this.addItemToInventory(q.rewardItemId, q.rewardItemCount);
    soundFX.playQuestComplete();
    const rewardMeta = getItemMeta(q.rewardItemId);
    this.showToast(
      `پاداش دریافت شد: +${q.rewardCoins} سکه و ${q.rewardItemCount}× ${rewardMeta.nameFa}! ✨`
    );
    this.emitHudState();
  }

  private gainXp(amount: number): void {
    this.playerXp += amount;
    let needed = this.getNextLevelXp();
    while (this.playerXp >= needed) {
      this.playerXp -= needed;
      this.playerLevel++;
      needed = this.getNextLevelXp();
      soundFX.playQuestComplete();
      this.pushLiveChat({
        senderFa: this.playerPreset.nameFa,
        senderKo: `레벨 ${this.playerLevel}`,
        roleFa: 'ارتقای سطح قهرمان!',
        portraitUrl: this.playerPortraitUrl,
        text: `تبریک! به سطح ${this.playerLevel} رسیدی و سلامت کامل بازیابی شد! 🌟`,
        accentColor: '#4CE8E0',
        durationMs: 4800,
      });
      this.health = this.maxHealth;
      this.hunger = this.maxHunger;
    }
  }

  private getNextLevelXp(): number {
    return 100 + (this.playerLevel - 1) * 60;
  }

  public pushLiveChat(params: {
    senderFa: string;
    senderKo: string;
    roleFa: string;
    portraitUrl: string;
    text: string;
    accentColor?: string;
    durationMs?: number;
  }): void {
    const msg: LiveChatMessage = {
      id: `chat_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      senderFa: params.senderFa,
      senderKo: params.senderKo,
      roleFa: params.roleFa,
      portraitUrl: params.portraitUrl,
      text: params.text,
      accentColor:
        params.accentColor ??
        ACCENT_PALETTE[Math.floor(Math.random() * ACCENT_PALETTE.length)],
      createdAt: Date.now(),
      durationMs: params.durationMs ?? 4800,
    };

    // Keep maximum 3 transient messages on screen so HUD never clutters
    this.liveChatFeed = [...this.liveChatFeed.slice(-2), msg];
    soundFX.playChatPop();
    this.emitHudState();
  }

  private pruneExpiredLiveChats(): void {
    if (this.liveChatFeed.length === 0) return;
    const now = Date.now();
    // Allow 480ms beyond durationMs for smooth CSS exit animation before unmounting
    const next = this.liveChatFeed.filter((m) => now - m.createdAt < m.durationMs + 480);
    if (next.length !== this.liveChatFeed.length) {
      this.liveChatFeed = next;
      this.emitHudState();
    }
  }

  private initScene(): void {
    const w = this.container.clientWidth || window.innerWidth;
    const h = this.container.clientHeight || window.innerHeight;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x84c8f8);
    this.scene.fog = new THREE.FogExp2(0x98d2fa, 0.0115);

    this.camera = new THREE.PerspectiveCamera(72, w / h, 0.1, 220);

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

    this.ambientLight = new THREE.AmbientLight(0xffffff, 0.62);
    this.hemiLight = new THREE.HemisphereLight(0xbde4ff, 0x6b8258, 0.42);
    this.sunLight = new THREE.DirectionalLight(0xfff4dc, 0.92);
    this.sunLight.position.set(40, 75, 30);
    this.scene.add(this.ambientLight, this.hemiLight, this.sunLight);

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

    const edgeGeo = new THREE.EdgesGeometry(new THREE.BoxGeometry(1.008, 1.008, 1.008));
    this.highlightBox = new THREE.LineSegments(
      edgeGeo,
      new THREE.LineBasicMaterial({ color: 0x11151c })
    );
    this.highlightBox.visible = false;
    this.scene.add(this.highlightBox);

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
      { id: BLOCK_IDS.NEON_CYAN, count: 24 },
    ];

    this.inventory = [
      { id: BLOCK_IDS.GRASS, count: 32 },
      { id: BLOCK_IDS.COBBLESTONE, count: 32 },
      { id: BLOCK_IDS.BRICK, count: 32 },
      { id: BLOCK_IDS.NEON_MAGENTA, count: 24 },
      { id: BLOCK_IDS.GOLD_BLOCK, count: 16 },
      { id: BLOCK_IDS.BASALT, count: 24 },
      { id: BLOCK_IDS.CHERRY_LEAVES, count: 24 },
      { id: BLOCK_IDS.GLASS, count: 24 },
      { id: BLOCK_IDS.OAK_LOG, count: 16 },
      { id: BLOCK_IDS.OAK_PLANKS, count: 32 },
      { id: BLOCK_IDS.CRAFTING_TABLE, count: 2 },
      { id: BLOCK_IDS.TNT, count: 6 },
      { id: 'tteokbokki', count: 5 },
      { id: 'bingsoo', count: 4 },
      { id: 'honey_tteok', count: 4 },
      null,
      null,
      null,
    ];
  }

  private initPlayerRig(): void {
    this.playerRig = buildKoreanCharacterRig(this.playerFace);
    this.scene.add(this.playerRig.root);

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

  private clearAllNpcs(): void {
    for (const npc of this.npcs) {
      this.scene.remove(npc.rig.root);
      npc.rig.dispose();
    }
    this.npcs = [];
  }

  private spawnVillageKoreanCharacters(): void {
    this.clearAllNpcs();
    const placements: Array<{
      presetId: string;
      x: number;
      z: number;
      yaw: number;
      heldItem: InventoryItemId | null;
    }> = [
      { presetId: 'seoyeon', x: 46.5, z: 45.2, yaw: 0.2, heldItem: BLOCK_IDS.CHERRY_LEAVES },
      { presetId: 'minjun', x: 50.5, z: 45.5, yaw: -0.3, heldItem: BLOCK_IDS.LANTERN },
      { presetId: 'jihoon', x: 48.5, z: 41.5, yaw: 0, heldItem: 'joseon_sword' },
      { presetId: 'halmeoni', x: 38.2, z: 46.5, yaw: Math.PI / 2, heldItem: 'kimbap' },
      { presetId: 'doyun', x: 57.5, z: 46.8, yaw: -Math.PI / 2, heldItem: 'diamond_pickaxe' },
      { presetId: 'haeun', x: 51.8, z: 51.5, yaw: -2.4, heldItem: BLOCK_IDS.HANOK_TILE },
      { presetId: 'subin', x: 44.2, z: 41.5, yaw: 0.4, heldItem: 'bingsoo' },
      { presetId: 'harabeoji', x: 61.5, z: 40.5, yaw: -0.8, heldItem: 'iron_axe' },
      { presetId: 'taeyang', x: 48.5, z: 55.2, yaw: Math.PI, heldItem: BLOCK_IDS.OAK_LOG },
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
      portraitUrl:
        this.presetPortraits[preset.id] ?? renderCharacterPortraitDataUrl(preset.face),
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
      greetCooldown: 2 + Math.random() * 6,
    };

    this.npcs.push(npc);
    return npc;
  }

  private initCherryBlossomParticles(): void {
    const count = 240;
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      positions[i * 3] = 18 + Math.random() * 60;
      positions[i * 3 + 1] = 16 + Math.random() * 18;
      positions[i * 3 + 2] = 20 + Math.random() * 58;
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

  public selectWorldBiome(biome: WorldBiomeId): void {
    if (this.worldBiome === biome && this.world.currentBiome === biome) {
      this.emitHudState();
      return;
    }
    this.worldBiome = biome;
    this.world.rebuildForBiome(biome);

    if (biome === 'seoul_night') {
      this.timeOfDay = 0.68; // Neon night illumination
    } else if (biome === 'jeju_island') {
      this.timeOfDay = 0.3; // Sunny island afternoon
    } else {
      this.timeOfDay = 0.22; // Spring cherry morning
    }

    this.spawnVillageKoreanCharacters();
    const spawnY = this.world.getSurfaceY(48, 52);
    this.playerPos.set(48.5, spawnY + 0.1, 52.5);
    this.playerVel.set(0, 0, 0);
    this.playerYaw = Math.PI;
    this.playerPitch = -0.05;

    const worldTitles: Record<WorldBiomeId, string> = {
      hanok_valley: 'دهکده سلطنتی هانوک 🌸',
      seoul_night: 'شب‌های نئونی سئول و رودخانه هان 🌃',
      jeju_island: 'جزیره آتشفشانی ججو و قله هالاسان 🏝️',
    };
    this.showToast(`سرزمین انتخاب شد: ${worldTitles[biome]}`);
    this.emitHudState();
  }

  public startGame(): void {
    this.started = true;
    this.activeModal = 'none';
    soundFX.unlockAndStartMusic();
    this.requestCanvasPointerLock();
    soundFX.playGreetingChime();

    // Welcome animated message from Seoyeon that glides in and leaves automatically!
    const seoyeon = KOREAN_CHARACTER_PRESETS.find((p) => p.id === 'seoyeon')!;
    this.pushLiveChat({
      senderFa: seoyeon.nameFa,
      senderKo: seoyeon.nameKo,
      roleFa: seoyeon.roleFa,
      portraitUrl: this.presetPortraits[seoyeon.id],
      text: `آنیونگ‌هاسیو ${this.playerPreset.nameFa}! به دنیای کی‌کرفت خوش آمدی، بیا نزدیک ما تا گپ بزنیم! 🌸`,
      accentColor: '#FF7EB6',
      durationMs: 5200,
    });

    this.emitHudState();
  }

  public returnToMainMenu(): void {
    this.started = false;
    this.activeModal = 'start';
    this.mouseDownLeft = false;
    this.mobileMoveX = 0;
    this.mobileMoveZ = 0;
    this.mobileJumping = false;
    this.exitPointerLock();
    soundFX.playUiClick();
    this.emitHudState();
  }

  public requestCanvasPointerLock(): void {
    try {
      const el = this.renderer.domElement;
      const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
      if (!isTouch && document.pointerLockElement !== el && el.requestPointerLock) {
        const res = el.requestPointerLock() as unknown as Promise<void> | undefined;
        if (res && typeof res.catch === 'function') {
          res.catch(() => {});
        }
      }
    } catch {
      // Safe fallback
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
    soundFX.playUiClick();
    if (modal !== 'none') {
      this.mouseDownLeft = false;
      this.mobileMoveX = 0;
      this.mobileMoveZ = 0;
      this.mobileJumping = false;
      this.exitPointerLock();
    } else if (this.started) {
      this.requestCanvasPointerLock();
    }
    this.emitHudState();
  }

  public setControlStyle(style: ControlStyle): void {
    this.controlStyle = style;
    soundFX.playUiClick();
    this.showToast(
      style === 'joystick'
        ? 'کنترل حرکت: جوی‌استیک آنالوگ ۳۶۰ درجه فعال شد'
        : 'کنترل حرکت: دکمه‌های جهتی گیم‌پد سه‌بعدی فعال شد'
    );
    this.emitHudState();
  }

  public setLookSensitivity(val: number): void {
    this.lookSensitivity = Math.max(0.4, Math.min(2.2, val));
    this.emitHudState();
  }

  public toggleMusic(): void {
    soundFX.setMusicEnabled(!soundFX.musicEnabled);
    this.emitHudState();
  }

  public toggleSfx(): void {
    soundFX.setSfxEnabled(!soundFX.sfxEnabled);
    this.emitHudState();
  }

  public toggleFlight(): void {
    this.isFlying = !this.isFlying;
    this.playerVel.y = 0;
    soundFX.playJump();
    this.showToast(
      this.isFlying
        ? 'پرواز آزاد فعال شد! با دکمه‌های بال/پایین اوج بگیر 🕊️'
        : 'فرود روی زمین — حالت راه رفتن عادی'
    );
    this.emitHudState();
  }

  public toggleMobileSprint(): void {
    this.mobileSprinting = !this.mobileSprinting;
    soundFX.playUiClick();
    this.emitHudState();
  }

  public selectCharacterPreset(preset: CharacterPreset): void {
    this.playerPreset = preset;
    this.playerFace = { ...preset.face };
    soundFX.playUiClick();
    this.applyPlayerAppearance();
  }

  public updatePlayerFace(partial: Partial<KoreanFaceConfig>): void {
    this.playerFace = { ...this.playerFace, ...partial };
    this.applyPlayerAppearance();
  }

  private applyPlayerAppearance(): void {
    this.playerRig.updateFaceConfig(this.playerFace);
    this.playerPortraitUrl = renderCharacterPortraitDataUrl(this.playerFace);

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
    soundFX.playUiClick();
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
    soundFX.playUiClick();
    if (this.gameMode === 'creative') {
      this.health = this.maxHealth;
      this.hunger = this.maxHunger;
      this.showToast('حالت خلاقیت فعال شد: بلوک بی‌نهایت، پرواز و شکستن فوری!');
    } else {
      this.isFlying = false;
      this.showToast('حالت بقا (Survival) فعال شد!');
    }
    this.emitHudState();
  }

  public toggleDayNight(): void {
    const currentlyNight = this.timeOfDay > 0.56 && this.timeOfDay < 0.94;
    this.timeOfDay = currentlyNight ? 0.23 : 0.68;
    soundFX.playUiClick();
    this.showToast(
      currentlyNight
        ? 'طلوع آفتاب درخشان در سرزمین کره‌ای ☀️'
        : 'شب فانوس‌ها و نورهای نئونی فرا رسید 🏮'
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
    const spawned = this.spawnNpcFromPreset(
      dokkaebiPreset,
      sx,
      sz,
      angle + Math.PI,
      'dokkaebi_club'
    );
    this.pushLiveChat({
      senderFa: spawned.preset.nameFa,
      senderKo: spawned.preset.nameKo,
      roleFa: 'مبارز افسانه‌ای شب',
      portraitUrl: spawned.portraitUrl,
      text: 'هاها! جرئت داری در میدان با گرز دوکه‌بی من روبه‌رو بشی؟ ⚔️',
      accentColor: '#FF5C77',
      durationMs: 4800,
    });
    soundFX.playSwordSwing();
    this.emitHudState();
  }

  public teleportToVillage(): void {
    const sy = this.world.getSurfaceY(48, 51);
    this.playerPos.set(48.5, sy + 0.1, 51.5);
    this.playerVel.set(0, 0, 0);
    this.playerYaw = Math.PI;
    this.playerPitch = -0.05;
    soundFX.playGreetingChime();
    this.showToast('انتقال سریع به میدان مرکزی!');
    this.emitHudState();
  }

  public selectHotbarSlot(index: number): void {
    if (index < 0 || index >= 9) return;
    this.hotbarIndex = index;
    this.miningElapsed = 0;
    soundFX.playUiClick();
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
    this.itemsCrafted++;
    this.gainXp(20);
    this.syncQuestProgress();
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
    this.socialInteractions++;
    this.gainXp(25);
    this.syncQuestProgress();
    soundFX.playGreetingChime();

    const dialogNpc = this.npcs.find((n) => n.id === this.activeDialogNpcId);
    const got = getItemMeta(offer.receiveId).nameFa;
    if (dialogNpc) {
      this.pushLiveChat({
        senderFa: dialogNpc.preset.nameFa,
        senderKo: dialogNpc.preset.nameKo,
        roleFa: dialogNpc.preset.roleFa,
        portraitUrl: dialogNpc.portraitUrl,
        text: `کامسامنیدا (ممنونم)! این ${offer.receiveCount} عدد «${got}» تقدیم به تو! 🤝`,
        accentColor: '#7AE582',
        durationMs: 4600,
      });
    }
    this.showToast(`معامله موفق! ${offer.receiveCount} عدد «${got}» دریافت کردی!`);
    this.emitHudState();
  }

  public toggleNpcFollow(entityId: string): void {
    const npc = this.npcs.find((n) => n.id === entityId);
    if (!npc || npc.preset.isHostile) return;
    npc.isFollowing = !npc.isFollowing;
    if (!this.talkedNpcSet.has(npc.id)) {
      this.talkedNpcSet.add(npc.id);
      this.socialInteractions++;
      this.syncQuestProgress();
    }
    soundFX.playGreetingChime();
    this.pushLiveChat({
      senderFa: npc.preset.nameFa,
      senderKo: npc.preset.nameKo,
      roleFa: npc.preset.roleFa,
      portraitUrl: npc.portraitUrl,
      text: npc.isFollowing
        ? 'با کمال میل همراهمت می‌شم! بزنم بریم ماجراجویی! ✨'
        : 'همین‌جا در دهکده می‌مانم؛ هر وقت خواستی دوباره صدایم کن!',
      accentColor: '#4CE8E0',
      durationMs: 4600,
    });
    this.emitHudState();
  }

  public sendQuickChatToNpc(npcId: string, playerMessageFa: string, npcReplyFa: string): void {
    const npc = this.npcs.find((n) => n.id === npcId);
    if (!this.talkedNpcSet.has(npcId)) {
      this.talkedNpcSet.add(npcId);
      this.socialInteractions++;
      this.gainXp(15);
      this.syncQuestProgress();
    }
    // Player message animates in first
    this.pushLiveChat({
      senderFa: this.playerPreset.nameFa,
      senderKo: this.playerPreset.nameKo,
      roleFa: 'شما',
      portraitUrl: this.playerPortraitUrl,
      text: playerMessageFa,
      accentColor: '#4CE8E0',
      durationMs: 4200,
    });
    // Villager animated reply arrives right after!
    if (npc) {
      window.setTimeout(() => {
        if (this.disposed) return;
        this.pushLiveChat({
          senderFa: npc.preset.nameFa,
          senderKo: npc.preset.nameKo,
          roleFa: npc.preset.roleFa,
          portraitUrl: npc.portraitUrl,
          text: npcReplyFa,
          accentColor: '#FF7EB6',
          durationMs: 4800,
        });
      }, 650);
    }
  }

  public triggerPrimaryActionTap(): void {
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
    } else {
      soundFX.playSwordSwing();
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
    }, 3200);
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
      return;
    }

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

    if (code === 'KeyJ' || code === 'KeyM') {
      e.preventDefault();
      this.setModal(this.activeModal === 'quests' ? 'none' : 'quests');
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
      } else {
        this.setModal('pause');
      }
      return;
    }

    if (this.activeModal !== 'none') return;

    if (code === 'KeyV') {
      this.cycleCameraMode();
    } else if (code === 'KeyG') {
      this.toggleGameMode();
    } else if (code === 'KeyZ') {
      this.toggleFlight();
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
    soundFX.unlockAndStartMusic();

    if (!this.pointerLocked) {
      this.requestCanvasPointerLock();
    }

    if (e.button === 0) {
      this.draggingLook = true;
      this.lastMouseX = e.clientX;
      this.lastMouseY = e.clientY;
      this.playerSwingAnim = 1;

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
    const sens = 0.0024 * this.lookSensitivity;

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
    soundFX.unlockAndStartMusic();
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
        const sens = 0.0052 * this.lookSensitivity;
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
    if (!this.talkedNpcSet.has(npc.id)) {
      this.talkedNpcSet.add(npc.id);
      this.socialInteractions++;
      this.gainXp(15);
      this.syncQuestProgress();
    }
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
      const dmg = held ? getItemMeta(held.id).attackDamage ?? 4 : 4;
      this.damageNpc(bestNpc, dmg, lookDir);
      soundFX.playSwordSwing();
      return true;
    }

    if (allowTalk) {
      this.activeDialogNpcId = bestNpc.id;
      if (!this.talkedNpcSet.has(bestNpc.id)) {
        this.talkedNpcSet.add(bestNpc.id);
        this.socialInteractions++;
        this.gainXp(15);
        this.syncQuestProgress();
      }
      this.setModal('npc_dialog');
      soundFX.playGreetingChime();
      return true;
    }

    return false;
  }

  private handleRightClickAction(): void {
    if (this.tryAttackOrInteractEntity(true)) {
      return;
    }

    const slot = this.hotbar[this.hotbarIndex];

    if (this.currentRayHit && this.currentRayHit.blockId === BLOCK_IDS.CRAFTING_TABLE) {
      this.setModal('inventory');
      return;
    }

    if (!slot) return;
    const meta = getItemMeta(slot.id);

    if (meta.category === 'food') {
      if (
        this.health < this.maxHealth ||
        this.hunger < this.maxHunger ||
        this.gameMode === 'creative'
      ) {
        this.health = Math.min(this.maxHealth, this.health + (meta.healAmount ?? 4));
        this.hunger = Math.min(this.maxHunger, this.hunger + (meta.hungerAmount ?? 5));
        if (this.gameMode !== 'creative') {
          slot.count -= 1;
          if (slot.count <= 0) this.hotbar[this.hotbarIndex] = null;
          this.refreshHeldItemMeshes();
        }
        this.playerSwingAnim = 1;
        soundFX.playEat();
        this.showToast(
          `نوش جان! ${meta.nameFa} (${meta.nameKo}) سلامت و انرژی را بازیابی کرد ❤️`
        );
        this.emitHudState();
      } else {
        this.showToast('سلامتی و انرژی شما کامل است!');
      }
      return;
    }

    if (meta.isBlock && typeof slot.id === 'number' && this.currentRayHit) {
      const px = this.currentRayHit.bx + this.currentRayHit.nx;
      const py = this.currentRayHit.by + this.currentRayHit.ny;
      const pz = this.currentRayHit.bz + this.currentRayHit.nz;

      if (!this.world.inBounds(px, py, pz)) return;

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
      this.gainXp(4);
      this.syncQuestProgress();
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
    this.gainXp(5);
    this.syncQuestProgress();
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
      [BLOCK_IDS.BASALT]: 0x363c47,
      [BLOCK_IDS.OAK_LOG]: 0x6b4d31,
      [BLOCK_IDS.OAK_PLANKS]: 0xba8e58,
      [BLOCK_IDS.CHERRY_LEAVES]: 0xffa8c4,
      [BLOCK_IDS.OAK_LEAVES]: 0x428a36,
      [BLOCK_IDS.HANOK_TILE]: 0x354156,
      [BLOCK_IDS.HANJI_WALL]: 0xfbf2df,
      [BLOCK_IDS.RED_PILLAR]: 0xb5282f,
      [BLOCK_IDS.LANTERN]: 0xffbf52,
      [BLOCK_IDS.NEON_CYAN]: 0x22e6e2,
      [BLOCK_IDS.NEON_MAGENTA]: 0xff4db8,
      [BLOCK_IDS.GOLD_BLOCK]: 0xf5c438,
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
        this.goldCoins += 45;
        this.gainXp(45);
        this.syncQuestProgress();
        const reward: InventoryItemId = Math.random() > 0.45 ? 'diamond' : 'gold_ingot';
        this.spawnPickup(reward, 1, npc.pos.clone().add(new THREE.Vector3(0, 0.7, 0)));
        this.pushLiveChat({
          senderFa: 'نگهبان جی‌هون',
          senderKo: '지훈',
          roleFa: 'محافظ دهکده',
          portraitUrl: this.presetPortraits['jihoon'] ?? this.playerPortraitUrl,
          text: 'آفرین جنگجوی شجاع! دوکه‌بی شکست خورد و دهکده در امان ماند! ⚔️✨',
          accentColor: '#FFD166',
          durationMs: 4800,
        });
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
      this.updateVillageLiveChatter(dt);
    } else {
      this.updateTitleScreenCamera(dt);
    }

    this.updateNpcs(dt);
    this.updatePickups(dt);
    this.updatePrimedTnts(dt);
    this.updateParticles(dt);
    this.pruneExpiredLiveChats();

    this.renderFrame();

    this.hudEmitTimer += dt;
    if (this.hudEmitTimer >= 0.14) {
      this.hudEmitTimer = 0;
      this.emitHudState();
    }
  };

  private updateVillageLiveChatter(dt: number): void {
    if (this.activeModal !== 'none') return;
    this.villageChatterTimer -= dt;
    if (this.villageChatterTimer > 0) return;
    this.villageChatterTimer = 15 + Math.random() * 10;

    // Pick a friendly Korean villager near the player or in the plaza to share a lively message!
    const friendlies = this.npcs.filter((n) => !n.preset.isHostile);
    if (friendlies.length === 0) return;

    const closeOnes = friendlies.filter((n) => n.pos.distanceTo(this.playerPos) < 16);
    const speaker =
      closeOnes.length > 0
        ? closeOnes[Math.floor(Math.random() * closeOnes.length)]
        : friendlies[Math.floor(Math.random() * friendlies.length)];

    const lines = speaker.preset.dialogLines;
    const line =
      lines && lines.length > 0
        ? lines[Math.floor(Math.random() * lines.length)]
        : speaker.preset.greetingFa;

    this.pushLiveChat({
      senderFa: speaker.preset.nameFa,
      senderKo: speaker.preset.nameKo,
      roleFa: speaker.preset.roleFa,
      portraitUrl: speaker.portraitUrl,
      text: line,
      durationMs: 4700,
    });
  }

  private updateTitleScreenCamera(_dt: number): void {
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
    if (this.activeModal === 'none') {
      const turnSpeed = 2.0 * dt * this.lookSensitivity;
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

    const sprinting =
      this.keys.has('ShiftLeft') || this.keys.has('ShiftRight') || this.mobileSprinting;
    const baseSpeed = this.isFlying
      ? 8.5
      : this.gameMode === 'creative'
      ? 7.0
      : sprinting
      ? 6.6
      : 4.7;

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

    const footBlock = this.world.getBlock(
      Math.floor(this.playerPos.x),
      Math.floor(this.playerPos.y + 0.5),
      Math.floor(this.playerPos.z)
    );
    const inWater = footBlock === BLOCK_IDS.WATER;

    const wantJump =
      this.activeModal === 'none' &&
      (this.keys.has('Space') || this.mobileJumping || this.mobileFlyUp);
    const wantDescend =
      this.activeModal === 'none' &&
      (this.keys.has('ControlLeft') || this.mobileFlyDown);

    if (this.isFlying) {
      let vy = 0;
      if (wantJump) vy += 6.2;
      if (wantDescend) vy -= 6.2;
      this.playerVel.y = vy;
    } else if (inWater) {
      this.playerVel.y -= 8.5 * dt;
      this.playerVel.y = Math.max(-2.8, this.playerVel.y);
      if (wantJump) {
        this.playerVel.y = 4.2;
      }
    } else {
      this.playerVel.y -= 23.5 * dt;
      this.playerVel.y = Math.max(-32, this.playerVel.y);
      if (wantJump && this.onGround) {
        this.playerVel.y = 8.2;
        this.onGround = false;
        soundFX.playJump();
      }
    }

    this.moveEntityWithVoxelAABB(this.playerPos, this.playerVel, dt, 0.3, 1.78, true);

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
    this.playerRig.bodyGroup.rotation.y = this.playerYaw + Math.PI;
    this.playerRig.headPivot.rotation.x = -this.playerPitch * 0.7;
    this.playerRig.animateWalk(
      horizSpeed,
      this.elapsedTotal,
      1 - this.playerSwingAnim > 0.99 ? 0 : this.playerSwingAnim
    );

    this.playerRig.root.visible = this.cameraMode !== 'first_person';

    const eye = this.getPlayerEyePos();
    const lookDir = this.getPlayerLookDir();

    if (this.cameraMode === 'first_person') {
      const bob =
        this.onGround && horizSpeed > 0.1
          ? Math.sin(this.elapsedTotal * 11) * 0.038 * horizSpeed
          : 0;
      this.camera.position.set(eye.x, eye.y + bob, eye.z);
      this.camera.rotation.order = 'YXZ';
      this.camera.rotation.y = this.playerYaw;
      this.camera.rotation.x = this.playerPitch;
      this.camera.rotation.z = 0;

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
      const forwardHoriz = new THREE.Vector3(
        -Math.sin(this.playerYaw),
        0.12,
        -Math.cos(this.playerYaw)
      ).normalize();
      const camRay = this.world.raycast(eye, forwardHoriz, 2.55);
      const safeDist = camRay ? Math.max(0.65, camRay.distance - 0.35) : 2.55;
      const camFront = eye.clone().addScaledVector(forwardHoriz, safeDist);
      this.camera.position.copy(camFront);
      this.camera.lookAt(this.playerPos.x, this.playerPos.y + 1.52, this.playerPos.z);
    }

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

    const nextY = pos.y + vel.y * dt;
    if (!collidesAt(pos.x, nextY, pos.z)) {
      pos.y = nextY;
    } else {
      if (vel.y < 0) {
        pos.y = Math.floor(nextY) + 1.0001;
        grounded = true;
        if (isPlayer && this.isFlying) {
          this.isFlying = false;
        }
      }
      vel.y = 0;
    }

    const nextX = pos.x + vel.x * dt;
    if (!collidesAt(nextX, pos.y + 0.02, pos.z)) {
      pos.x = nextX;
    } else if (!isPlayer && grounded && !collidesAt(nextX, pos.y + 1.05, pos.z)) {
      pos.y += 1.02;
      pos.x = nextX;
    } else if (isPlayer && grounded && !collidesAt(nextX, pos.y + 1.05, pos.z)) {
      // Smooth mobile auto-step over 1-block curbs/stairs!
      pos.y += 1.02;
      pos.x = nextX;
    } else {
      vel.x = 0;
    }

    const nextZ = pos.z + vel.z * dt;
    if (!collidesAt(pos.x, pos.y + 0.02, nextZ)) {
      pos.z = nextZ;
    } else if (!isPlayer && grounded && !collidesAt(pos.x, pos.y + 1.05, nextZ)) {
      pos.y += 1.02;
      pos.z = nextZ;
    } else if (isPlayer && grounded && !collidesAt(pos.x, pos.y + 1.05, nextZ)) {
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
    const isNight = this.timeOfDay > 0.58 && this.timeOfDay < 0.92;
    if (this.started && isNight && this.gameMode === 'survival') {
      this.dokkaebiSpawnTimer -= dt;
      const hostileCount = this.npcs.filter((n) => n.preset.isHostile).length;
      if (this.dokkaebiSpawnTimer <= 0 && hostileCount < 2) {
        this.dokkaebiSpawnTimer = 25;
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
    let closestDist = 4.5;

    for (const npc of this.npcs) {
      npc.blinkTimer -= dt;
      if (npc.blinkTimer <= 0) {
        npc.isBlinking = !npc.isBlinking;
        npc.blinkTimer = npc.isBlinking ? 0.14 : 2.2 + Math.random() * 3.8;
        npc.rig.setBlinking(npc.isBlinking);
      }

      if (npc.hurtFlash > 0) npc.hurtFlash = Math.max(0, npc.hurtFlash - dt);
      if (npc.attackCooldown > 0) npc.attackCooldown = Math.max(0, npc.attackCooldown - dt);
      if (npc.swingAnim > 0) npc.swingAnim = Math.max(0, npc.swingAnim - dt * 4);
      if (npc.greetCooldown > 0) npc.greetCooldown = Math.max(0, npc.greetCooldown - dt);

      const distToPlayer = npc.pos.distanceTo(this.playerPos);

      if (!npc.preset.isHostile && distToPlayer < closestDist) {
        closestDist = distToPlayer;
        closestFriendly = npc;

        // Spontaneous animated greeting bubble when player approaches a Korean villager!
        if (
          this.started &&
          this.activeModal === 'none' &&
          distToPlayer < 3.4 &&
          npc.greetCooldown <= 0
        ) {
          npc.greetCooldown = 28;
          this.pushLiveChat({
            senderFa: npc.preset.nameFa,
            senderKo: npc.preset.nameKo,
            roleFa: npc.preset.roleFa,
            portraitUrl: npc.portraitUrl,
            text: npc.preset.greetingFa,
            durationMs: 4500,
          });
        }
      }

      if (npc.preset.isHostile) {
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
        if (
          distToPlayer <= 1.85 &&
          npc.attackCooldown <= 0 &&
          this.started &&
          this.gameMode === 'survival'
        ) {
          npc.attackCooldown = 1.4;
          npc.swingAnim = 1;
          this.health = Math.max(1, this.health - 2);
          soundFX.playSwordSwing();
          this.showToast('دوکه‌بی ضربه زد! با شمشیر چوسان دفاع کن یا غذا بخور!');
        }
      } else {
        const nearestHostile = this.npcs.find(
          (other) => other.preset.isHostile && other.pos.distanceTo(npc.pos) < 12
        );

        if ((npc.preset.id === 'jihoon' || npc.isFollowing) && nearestHostile) {
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
            this.damageNpc(nearestHostile, 6, new THREE.Vector3(dx, 0, dz).normalize());
          }
        } else if (npc.isFollowing) {
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
          npc.aiTimer -= dt;
          if (npc.aiTimer <= 0) {
            npc.aiTimer = 2.0 + Math.random() * 3.5;
            npc.moving = Math.random() > 0.45;
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
            npc.targetYaw = Math.atan2(
              this.playerPos.x - npc.pos.x,
              this.playerPos.z - npc.pos.z
            );
          } else if (npc.moving) {
            const aheadX = Math.floor(npc.pos.x + Math.sin(npc.targetYaw) * 1.2);
            const aheadZ = Math.floor(npc.pos.z + Math.cos(npc.targetYaw) * 1.2);
            const aheadSurface = this.world.getSurfaceY(aheadX, aheadZ);
            if (aheadSurface <= WATER_LEVEL) {
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

      npc.vel.y = Math.max(-28, npc.vel.y - 22 * dt);
      this.moveEntityWithVoxelAABB(npc.pos, npc.vel, dt, 0.28, 1.75, false);

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
      if (
        !this.world.isSolid(
          Math.floor(p.pos.x),
          Math.floor(nextY - 0.15),
          Math.floor(p.pos.z)
        )
      ) {
        p.pos.y = nextY;
      } else {
        p.vel.y = 0;
        p.vel.x *= 0.85;
        p.vel.z *= 0.85;
      }
      p.pos.x += p.vel.x * dt;
      p.pos.z += p.vel.z * dt;

      p.mesh.position.set(
        p.pos.x,
        p.pos.y + Math.sin(this.elapsedTotal * 4 + i) * 0.08,
        p.pos.z
      );
      p.mesh.rotation.y += dt * 2.4;

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
    this.timeOfDay += dt / 340;
    if (this.timeOfDay >= 1) {
      this.timeOfDay -= 1;
      this.dayCount++;
    }

    const sunAngle = this.timeOfDay * Math.PI * 2;
    const sunElev = Math.sin(sunAngle);

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

    const daySky =
      this.worldBiome === 'jeju_island'
        ? new THREE.Color(0x5ec8f8)
        : new THREE.Color(0x80c7f9);
    const sunsetSky = new THREE.Color(0xeb9872);
    const nightSky =
      this.worldBiome === 'seoul_night'
        ? new THREE.Color(0x141736)
        : new THREE.Color(0x11192e);

    let skyColor: THREE.Color;
    if (sunElev > 0.22) {
      skyColor = daySky;
      this.sunLight.intensity = 0.92;
      this.ambientLight.intensity = 0.64;
    } else if (sunElev > -0.14) {
      const t = (sunElev + 0.14) / 0.36;
      skyColor = nightSky
        .clone()
        .lerp(sunsetSky, Math.sin(t * Math.PI))
        .lerp(daySky, t);
      this.sunLight.intensity = 0.25 + t * 0.67;
      this.ambientLight.intensity = 0.38 + t * 0.26;
    } else {
      skyColor = nightSky;
      this.sunLight.intensity = 0.22;
      this.ambientLight.intensity = this.worldBiome === 'seoul_night' ? 0.52 : 0.4;
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
      portraitUrl: npc.portraitUrl,
      isFollowing: npc.isFollowing,
      hp: Math.ceil(npc.hp),
      maxHp: npc.maxHp,
    };
  }

  public emitHudState(): void {
    const isNight = this.timeOfDay > 0.56 && this.timeOfDay < 0.94;
    let timeLabelFa = 'روز بهاری';
    if (this.timeOfDay >= 0.46 && this.timeOfDay <= 0.56) timeLabelFa = 'غروب طلایی';
    else if (isNight) timeLabelFa = 'شب فانوس‌ها';
    else if (this.timeOfDay >= 0.94 || this.timeOfDay < 0.08) timeLabelFa = 'طلوع صبحگاهی';

    const nearby = this.npcs.find((n) => n.id === this.nearbyNpcId);
    const dialogNpc = this.npcs.find((n) => n.id === this.activeDialogNpcId);

    const radarDots: RadarDot[] = this.npcs
      .map((n) => ({
        id: n.id,
        dx: n.pos.x - this.playerPos.x,
        dz: n.pos.z - this.playerPos.z,
        kind: n.preset.isHostile
          ? ('hostile' as const)
          : n.isFollowing
          ? ('companion' as const)
          : ('villager' as const),
        nameFa: n.preset.nameFa,
      }))
      .filter((d) => Math.hypot(d.dx, d.dz) <= 32);

    this.onHudUpdate({
      started: this.started,
      activeModal: this.activeModal,
      worldBiome: this.worldBiome,
      health: Math.round(this.health),
      maxHealth: this.maxHealth,
      hunger: Math.round(this.hunger),
      maxHunger: this.maxHunger,
      hotbarIndex: this.hotbarIndex,
      hotbar: this.hotbar.map((s) => (s ? { ...s } : null)),
      inventory: this.inventory.map((s) => (s ? { ...s } : null)),
      cameraMode: this.cameraMode,
      gameMode: this.gameMode,
      isFlying: this.isFlying,
      sprinting: this.mobileSprinting,
      timeLabelFa,
      isNight,
      dayCount: this.dayCount,
      coords: {
        x: Math.floor(this.playerPos.x),
        y: Math.floor(this.playerPos.y),
        z: Math.floor(this.playerPos.z),
      },
      playerYaw: this.playerYaw,
      fps: this.fps,
      playerNameFa: this.playerPreset.nameFa,
      playerNameKo: this.playerPreset.nameKo,
      playerFace: { ...this.playerFace },
      playerPortraitUrl: this.playerPortraitUrl,
      playerLevel: this.playerLevel,
      playerXp: this.playerXp,
      nextLevelXp: this.getNextLevelXp(),
      goldCoins: this.goldCoins,
      quests: this.quests.map((q) => ({ ...q })),
      liveChatFeed: [...this.liveChatFeed],
      radarDots,
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
      controlStyle: this.controlStyle,
      lookSensitivity: this.lookSensitivity,
      musicEnabled: soundFX.musicEnabled,
      sfxEnabled: soundFX.sfxEnabled,
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
