export type BlockId =
  | 0 // air
  | 1 // grass
  | 2 // dirt
  | 3 // stone
  | 4 // cobblestone
  | 5 // oak_log
  | 6 // oak_planks
  | 7 // oak_leaves
  | 8 // cherry_leaves (벚꽃)
  | 9 // sand
  | 10 // water
  | 11 // coal_ore
  | 12 // iron_ore
  | 13 // gold_ore
  | 14 // diamond_ore
  | 15 // hanok_tile (기와)
  | 16 // hanji_wall (한지창)
  | 17 // red_pillar (단청 기둥)
  | 18 // lantern (청사초롱)
  | 19 // glass
  | 20 // brick (화강암 벽돌)
  | 21 // crafting_table
  | 22 // tnt
  | 23 // neon_cyan (서울 네온)
  | 24 // neon_magenta (케이팝 네온)
  | 25 // basalt (제주 현무암)
  | 26; // gold_block (황금 블록)

export type ToolOrItemId =
  | 'diamond_pickaxe'
  | 'iron_axe'
  | 'joseon_sword'
  | 'kimbap'
  | 'tteokbokki'
  | 'bingsoo'
  | 'honey_tteok'
  | 'coal'
  | 'iron_ingot'
  | 'gold_ingot'
  | 'diamond';

export type InventoryItemId = BlockId | ToolOrItemId;

export interface InventorySlot {
  id: InventoryItemId;
  count: number;
}

export interface ItemMetadata {
  id: InventoryItemId;
  nameFa: string;
  nameKo: string;
  category: 'block' | 'tool' | 'food' | 'material';
  isBlock: boolean;
  hardness?: number; // seconds to break by hand
  preferredTool?: 'pickaxe' | 'axe';
  transparent?: boolean;
  liquid?: boolean;
  emitsLight?: boolean;
  healAmount?: number;
  hungerAmount?: number;
  attackDamage?: number;
}

export type SkinToneId =
  | 'porcelain'
  | 'warm_ivory'
  | 'natural_peach'
  | 'honey_warm'
  | 'dokkaebi_bronze';

export type EyeStyleId =
  | 'monolid'
  | 'soft_double'
  | 'eye_smile'
  | 'sharp_warrior'
  | 'gentle_elder'
  | 'fierce_dokkaebi';

export type BrowStyleId =
  | 'straight_soft'
  | 'straight_bold'
  | 'arched_idol'
  | 'elder_silver'
  | 'warrior_slant';

export type HairStyleId =
  | 'comma_twoblock'
  | 'seethrough_long'
  | 'joseon_gat'
  | 'idol_layered'
  | 'halmeoni_perm'
  | 'binyeo_bun'
  | 'student_cut'
  | 'satgat_farmer'
  | 'dokkaebi_horn';

export type LipStyleId =
  | 'natural_warm'
  | 'kbeauty_rose'
  | 'coral_gradient'
  | 'berry_tint'
  | 'elder_matte';

export type GlassesStyleId = 'none' | 'seoul_round' | 'tinted_idol';

export type BeautyMarkId = 'none' | 'under_eye' | 'cheek';

export type OutfitStyleId =
  | 'seoul_street'
  | 'hanbok_pink'
  | 'hanbok_royal'
  | 'joseon_guard'
  | 'halmeoni_vest'
  | 'carpenter_hemp'
  | 'student_hoodie'
  | 'hanbok_apron'
  | 'farmer_linen'
  | 'dokkaebi_armor';

export interface KoreanFaceConfig {
  skinTone: SkinToneId;
  eyeStyle: EyeStyleId;
  browStyle: BrowStyleId;
  hairStyle: HairStyleId;
  hairColor: string;
  lipStyle: LipStyleId;
  blushIntensity: number;
  glasses: GlassesStyleId;
  beautyMark: BeautyMarkId;
  outfitStyle: OutfitStyleId;
}

export interface TradeOffer {
  id: string;
  giveId: InventoryItemId;
  giveCount: number;
  receiveId: InventoryItemId;
  receiveCount: number;
  labelFa: string;
}

export interface CharacterPreset {
  id: string;
  nameFa: string;
  nameKo: string;
  roleFa: string;
  greetingKo: string;
  greetingFa: string;
  bioFa: string;
  dialogLines: string[];
  face: KoreanFaceConfig;
  isPlayable: boolean;
  isHostile?: boolean;
  trades: TradeOffer[];
}

export type WorldBiomeId = 'hanok_valley' | 'seoul_night' | 'jeju_island';
export type ControlStyle = 'joystick' | 'dpad';
export type MenuPageId =
  | 'hub'
  | 'worlds'
  | 'face_studio'
  | 'villagers'
  | 'quests'
  | 'settings';

export type CameraMode = 'first_person' | 'third_back' | 'third_front';
export type GameMode = 'survival' | 'creative';
export type ActiveModal =
  | 'start'
  | 'none'
  | 'pause'
  | 'inventory'
  | 'customizer'
  | 'npc_dialog'
  | 'quests'
  | 'settings'
  | 'help';

export interface NpcStatusSnapshot {
  entityId: string;
  preset: CharacterPreset;
  portraitUrl: string;
  isFollowing: boolean;
  hp: number;
  maxHp: number;
}

export interface CraftingRecipe {
  id: string;
  nameFa: string;
  resultId: InventoryItemId;
  resultCount: number;
  ingredients: Array<{ id: InventoryItemId; count: number }>;
}

export interface LiveChatMessage {
  id: string;
  senderFa: string;
  senderKo: string;
  roleFa: string;
  portraitUrl: string;
  text: string;
  accentColor: string;
  createdAt: number;
  durationMs: number;
}

export interface RadarDot {
  id: string;
  dx: number; // relative X from player
  dz: number; // relative Z from player
  kind: 'villager' | 'companion' | 'hostile';
  nameFa: string;
}

export interface QuestProgress {
  id: string;
  titleFa: string;
  descFa: string;
  category: 'mine' | 'build' | 'social' | 'combat' | 'craft';
  current: number;
  target: number;
  rewardXp: number;
  rewardCoins: number;
  rewardItemId: InventoryItemId;
  rewardItemCount: number;
  claimed: boolean;
}

export interface HudState {
  started: boolean;
  activeModal: ActiveModal;
  worldBiome: WorldBiomeId;
  health: number;
  maxHealth: number;
  hunger: number;
  maxHunger: number;
  hotbarIndex: number;
  hotbar: Array<InventorySlot | null>;
  inventory: Array<InventorySlot | null>;
  cameraMode: CameraMode;
  gameMode: GameMode;
  isFlying: boolean;
  sprinting: boolean;
  timeLabelFa: string;
  isNight: boolean;
  dayCount: number;
  coords: { x: number; y: number; z: number };
  playerYaw: number;
  fps: number;
  playerNameFa: string;
  playerNameKo: string;
  playerFace: KoreanFaceConfig;
  playerPortraitUrl: string;
  playerLevel: number;
  playerXp: number;
  nextLevelXp: number;
  goldCoins: number;
  quests: QuestProgress[];
  liveChatFeed: LiveChatMessage[];
  radarDots: RadarDot[];
  nearbyNpc: NpcStatusSnapshot | null;
  activeDialogNpc: NpcStatusSnapshot | null;
  companionsCount: number;
  totalNpcsInWorld: number;
  dokkaebiDefeated: number;
  blocksMined: number;
  blocksPlaced: number;
  pointerLocked: boolean;
  toastMessage: string | null;
  breakingProgress: number; // 0..1
  targetBlockNameFa: string | null;
  controlStyle: ControlStyle;
  lookSensitivity: number; // 0.5 .. 2.0
  musicEnabled: boolean;
  sfxEnabled: boolean;
}
