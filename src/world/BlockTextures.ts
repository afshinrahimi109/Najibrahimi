import * as THREE from 'three';
import { BLOCK_IDS } from '../data/items';
import { BlockId, InventoryItemId } from '../types/game';

export const TILE_SIZE = 32;
export const ATLAS_COLS = 8;
export const ATLAS_ROWS = 8;

// Tile indices inside the 8x8 atlas
export const TILE_INDEX = {
  GRASS_TOP: 0,
  GRASS_SIDE: 1,
  DIRT: 2,
  STONE: 3,
  COBBLESTONE: 4,
  OAK_LOG_SIDE: 5,
  OAK_LOG_TOP: 6,
  OAK_PLANKS: 7,
  OAK_LEAVES: 8,
  CHERRY_LEAVES: 9,
  SAND: 10,
  WATER: 11,
  COAL_ORE: 12,
  IRON_ORE: 13,
  GOLD_ORE: 14,
  DIAMOND_ORE: 15,
  HANOK_TILE_TOP: 16,
  HANOK_TILE_SIDE: 17,
  HANJI_WALL: 18,
  RED_PILLAR_SIDE: 19,
  RED_PILLAR_TOP: 20,
  LANTERN_SIDE: 21,
  LANTERN_TOP: 22,
  GLASS: 23,
  BRICK: 24,
  CRAFT_TOP: 25,
  CRAFT_SIDE: 26,
  TNT_SIDE: 27,
  TNT_TOP: 28,
  TNT_BOTTOM: 29,
  NEON_CYAN: 30,
  NEON_MAGENTA: 31,
  BASALT: 32,
  GOLD_BLOCK: 33,
};

// deterministic pseudo-random for crisp repeatable pixel noise
function hash2(x: number, y: number, seed: number): number {
  let n = Math.imul(x * 374761393 + y * 668265263 + seed * 1442695041, 1274126177);
  n = (n ^ (n >>> 13)) >>> 0;
  return (n & 0xffff) / 0xffff;
}

function shade(hex: string, delta: number): string {
  const num = parseInt(hex.replace('#', ''), 16);
  const r = Math.min(255, Math.max(0, ((num >> 16) & 0xff) + delta));
  const g = Math.min(255, Math.max(0, ((num >> 8) & 0xff) + delta));
  const b = Math.min(255, Math.max(0, (num & 0xff) + delta));
  return `rgb(${r},${g},${b})`;
}

function drawPixelTile(
  ctx: CanvasRenderingContext2D,
  tileIdx: number,
  drawer: (px: (x: number, y: number, color: string) => void) => void
): void {
  const col = tileIdx % ATLAS_COLS;
  const row = Math.floor(tileIdx / ATLAS_COLS);
  const ox = col * TILE_SIZE;
  const oy = row * TILE_SIZE;

  // Draw on 16x16 logical Minecraft pixel grid scaled 2x -> 32x32!
  const px = (x: number, y: number, color: string) => {
    if (x < 0 || x >= 16 || y < 0 || y >= 16) return;
    ctx.fillStyle = color;
    ctx.fillRect(ox + x * 2, oy + y * 2, 2, 2);
  };
  drawer(px);
}

export interface BlockTextureSystem {
  atlasTexture: THREE.CanvasTexture;
  opaqueMaterial: THREE.MeshLambertMaterial;
  translucentMaterial: THREE.MeshLambertMaterial;
  getFaceTile: (blockId: BlockId, faceDir: 'top' | 'bottom' | 'side') => number;
  getTileUV: (tileIdx: number) => { u0: number; v0: number; u1: number; v1: number };
  getSingleBlockMaterials: (blockId: number) => THREE.Material[];
  itemIconUrls: Record<string, string>;
}

let cachedSystem: BlockTextureSystem | null = null;

export function getBlockTextureSystem(): BlockTextureSystem {
  if (cachedSystem) return cachedSystem;

  const atlasCanvas = document.createElement('canvas');
  atlasCanvas.width = ATLAS_COLS * TILE_SIZE;
  atlasCanvas.height = ATLAS_ROWS * TILE_SIZE;
  const ctx = atlasCanvas.getContext('2d')!;

  // 0. GRASS_TOP (lush spring meadow green)
  drawPixelTile(ctx, TILE_INDEX.GRASS_TOP, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const r = hash2(x, y, 1);
        px(x, y, shade('#64B647', Math.floor((r - 0.5) * 28)));
      }
    }
  });

  // 2. DIRT
  drawPixelTile(ctx, TILE_INDEX.DIRT, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const r = hash2(x, y, 2);
        const base = r > 0.86 ? '#6E4E34' : '#866042';
        px(x, y, shade(base, Math.floor((r - 0.5) * 22)));
      }
    }
  });

  // 1. GRASS_SIDE
  drawPixelTile(ctx, TILE_INDEX.GRASS_SIDE, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const overhang = 3 + Math.floor(hash2(x, 0, 11) * 3);
        const r = hash2(x, y, 3);
        if (y < overhang) {
          px(x, y, shade('#64B647', Math.floor((r - 0.5) * 26)));
        } else if (y === overhang) {
          px(x, y, '#4A8C34');
        } else {
          px(x, y, shade('#866042', Math.floor((r - 0.5) * 24)));
        }
      }
    }
  });

  // 3. STONE
  const fillStoneBase = (px: (x: number, y: number, c: string) => void, seed: number) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const r = hash2(x, y, seed);
        const streak = hash2(Math.floor(x / 2), y, seed + 5);
        px(x, y, shade('#83878D', Math.floor((r * 0.6 + streak * 0.4 - 0.5) * 30)));
      }
    }
  };
  drawPixelTile(ctx, TILE_INDEX.STONE, (px) => fillStoneBase(px, 4));

  // 4. COBBLESTONE
  drawPixelTile(ctx, TILE_INDEX.COBBLESTONE, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const cell = ((x + (y % 4 >= 2 ? 2 : 0)) % 4 === 0) || (y % 4 === 0);
        const r = hash2(x, y, 5);
        px(x, y, cell ? '#55585E' : shade('#7D8188', Math.floor((r - 0.5) * 28)));
      }
    }
  });

  // 5. OAK_LOG_SIDE
  drawPixelTile(ctx, TILE_INDEX.OAK_LOG_SIDE, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const groove = x % 4 === 0;
        const r = hash2(x, Math.floor(y / 2), 6);
        px(x, y, groove ? '#4D3621' : shade('#6B4D31', Math.floor((r - 0.5) * 24)));
      }
    }
  });

  // 6. OAK_LOG_TOP
  drawPixelTile(ctx, TILE_INDEX.OAK_LOG_TOP, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const dist = Math.max(Math.abs(x - 7.5), Math.abs(y - 7.5));
        if (dist >= 6.5) px(x, y, '#5E432A');
        else if (Math.round(dist) % 2 === 0) px(x, y, '#B89462');
        else px(x, y, '#9E7B4D');
      }
    }
  });

  // 7. OAK_PLANKS
  drawPixelTile(ctx, TILE_INDEX.OAK_PLANKS, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const seamY = y % 4 === 3;
        const seamX = (y < 4 || (y >= 8 && y < 12) ? x === 7 : x === 13);
        const r = hash2(x, y, 8);
        if (seamY || seamX) px(x, y, '#85623B');
        else px(x, y, shade('#BA8E58', Math.floor((r - 0.5) * 18)));
      }
    }
  });

  // 8. OAK_LEAVES
  drawPixelTile(ctx, TILE_INDEX.OAK_LEAVES, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const r = hash2(x, y, 9);
        px(x, y, r > 0.72 ? '#2E6926' : r > 0.32 ? '#428A36' : '#52A343');
      }
    }
  });

  // 9. CHERRY_LEAVES (Korean Spring Cherry Blossom 벚꽃!)
  drawPixelTile(ctx, TILE_INDEX.CHERRY_LEAVES, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const r = hash2(x, y, 10);
        if (r > 0.8) px(x, y, '#FFF0F5');
        else if (r > 0.42) px(x, y, '#FFB5CB');
        else if (r > 0.14) px(x, y, '#F288AA');
        else px(x, y, '#D8658B');
      }
    }
  });

  // 10. SAND
  drawPixelTile(ctx, TILE_INDEX.SAND, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const r = hash2(x, y, 12);
        px(x, y, shade('#E6D5A1', Math.floor((r - 0.5) * 20)));
      }
    }
  });

  // 11. WATER
  drawPixelTile(ctx, TILE_INDEX.WATER, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const wave = (x + y * 2) % 7 === 0;
        const r = hash2(x, y, 13);
        px(x, y, wave ? '#6BC5F8' : shade('#2F89D8', Math.floor((r - 0.5) * 18)));
      }
    }
  });

  // 12..15 ORES (Coal, Iron, Gold, Diamond)
  const oreSpecs: Array<[number, string, string]> = [
    [TILE_INDEX.COAL_ORE, '#222428', '#383B42'],
    [TILE_INDEX.IRON_ORE, '#E0B596', '#F5D6BE'],
    [TILE_INDEX.GOLD_ORE, '#F5C438', '#FFF08A'],
    [TILE_INDEX.DIAMOND_ORE, '#32E6DF', '#B8FFFF'],
  ];
  const flecks = [
    [3, 4], [4, 4], [4, 5],
    [10, 3], [11, 3], [11, 4],
    [6, 9], [7, 9], [7, 10], [8, 10],
    [12, 11], [13, 11], [12, 12],
    [3, 12], [4, 13],
  ];
  for (const [idx, mainCol, hiCol] of oreSpecs) {
    drawPixelTile(ctx, idx, (px) => {
      fillStoneBase(px, idx + 30);
      flecks.forEach(([fx, fy], i) => {
        px(fx, fy, i % 3 === 0 ? hiCol : mainCol);
      });
    });
  }

  // 16 & 17. HANOK_TILE (Korean Traditional Dark Slate Giwa 기와 Roof!)
  drawPixelTile(ctx, TILE_INDEX.HANOK_TILE_TOP, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        // Curved concave/convex Korean roof tile ribs!
        const rib = x % 4;
        const rowLine = y % 8 === 7;
        if (rowLine) px(x, y, '#1E2533');
        else if (rib === 0) px(x, y, '#47556E');
        else if (rib === 1) px(x, y, '#354156');
        else px(x, y, '#293345');
      }
    }
  });
  drawPixelTile(ctx, TILE_INDEX.HANOK_TILE_SIDE, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        if (y >= 11 && (x % 4 === 1 || x % 4 === 2)) {
          // Circular Korean Sumaksae (수막새) roof-end medallion!
          px(x, y, '#63738F');
        } else {
          px(x, y, x % 4 === 0 ? '#46546D' : '#2C3649');
        }
      }
    }
  });

  // 18. HANJI_WALL (Traditional Korean Wooden Lattice + Warm Cream Hanji Paper 한지창!)
  drawPixelTile(ctx, TILE_INDEX.HANJI_WALL, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const border = x === 0 || x === 15 || y === 0 || y === 15;
        const lattice = x === 5 || x === 10 || y === 5 || y === 10;
        if (border) px(x, y, '#7A4F2B');
        else if (lattice) px(x, y, '#9C683B');
        else {
          const r = hash2(x, y, 44);
          px(x, y, shade('#FBF2DF', Math.floor((r - 0.5) * 10)));
        }
      }
    }
  });

  // 19 & 20. RED_PILLAR (Korean Palace Dancheong Lacquered Pillar 단청 기둥!)
  drawPixelTile(ctx, TILE_INDEX.RED_PILLAR_SIDE, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        if (y === 0 || y === 1) px(x, y, '#2D8A6E'); // Dancheong celadon green band!
        else if (y === 2) px(x, y, '#F2C94C'); // Gold accent!
        else {
          const shadeX = x < 3 || x > 12 ? -22 : x > 6 && x < 10 ? 14 : 0;
          px(x, y, shade('#B5282F', shadeX));
        }
      }
    }
  });
  drawPixelTile(ctx, TILE_INDEX.RED_PILLAR_TOP, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        px(x, y, x === 0 || x === 15 || y === 0 || y === 15 ? '#2D8A6E' : '#9E2228');
      }
    }
  });

  // 21 & 22. LANTERN (Korean Cheongsachorong 청사초롱 Red & Blue Silk Glowing Lantern!)
  drawPixelTile(ctx, TILE_INDEX.LANTERN_SIDE, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const frame = x === 0 || x === 15 || y === 0 || y === 15;
        const distCenter = Math.hypot(x - 7.5, y - 7.5);
        if (frame) {
          px(x, y, '#3A261A');
        } else if (y < 6) {
          // Traditional royal blue silk upper shade
          px(x, y, distCenter < 5 ? '#497CE8' : '#2A4FA8');
        } else if (y > 10) {
          // Traditional crimson silk lower shade
          px(x, y, distCenter < 5 ? '#F25260' : '#B82838');
        } else {
          // Warm golden glowing core!
          px(x, y, distCenter < 4 ? '#FFF7C2' : '#FFBF52');
        }
      }
    }
  });
  drawPixelTile(ctx, TILE_INDEX.LANTERN_TOP, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        px(x, y, x > 4 && x < 11 && y > 4 && y < 11 ? '#FFE484' : '#2A4FA8');
      }
    }
  });

  // 23. GLASS
  drawPixelTile(ctx, TILE_INDEX.GLASS, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const edge = x === 0 || x === 15 || y === 0 || y === 15;
        const streak = (x + y === 5) || (x + y === 6) || (x + y === 10);
        if (edge) px(x, y, '#B8E8F5');
        else if (streak) px(x, y, '#FFFFFF');
        else px(x, y, '#82C8DC');
      }
    }
  });

  // 24. BRICK (Joseon Palace Granite Stone Brick 화강석 벽돌)
  drawPixelTile(ctx, TILE_INDEX.BRICK, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const mortarY = y % 4 === 0;
        const offset = Math.floor(y / 4) % 2 === 0 ? 0 : 4;
        const mortarX = (x + offset) % 8 === 0;
        const r = hash2(x, y, 51);
        if (mortarY || mortarX) px(x, y, '#8C8982');
        else px(x, y, shade('#C9C5BC', Math.floor((r - 0.5) * 18)));
      }
    }
  });

  // 25 & 26. CRAFTING_TABLE
  drawPixelTile(ctx, TILE_INDEX.CRAFT_TOP, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const border = x < 2 || x > 13 || y < 2 || y > 13;
        const grid = x === 6 || x === 10 || y === 6 || y === 10;
        if (border) px(x, y, '#6E4726');
        else if (grid) px(x, y, '#4A2E18');
        else px(x, y, '#B88450');
      }
    }
  });
  drawPixelTile(ctx, TILE_INDEX.CRAFT_SIDE, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        if (y < 3) px(x, y, '#6E4726');
        else if ((x === 4 || x === 5) && y > 5 && y < 13) px(x, y, '#9AA4B2'); // saw/tool detail
        else px(x, y, y % 4 === 0 ? '#7D5430' : '#AC7D4A');
      }
    }
  });

  // 27, 28, 29. TNT
  drawPixelTile(ctx, TILE_INDEX.TNT_SIDE, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        if (y >= 5 && y <= 10) {
          const textPixel =
            (y >= 6 && y <= 9 && (x === 3 || x === 7 || x === 9 || x === 13)) ||
            (y === 6 && (x === 2 || x === 4 || x === 12 || x === 14)) ||
            (y === 7 && x === 8);
          px(x, y, textPixel ? '#181818' : '#F4F4F0');
        } else {
          px(x, y, x % 4 === 0 ? '#B5241C' : '#DC352B');
        }
      }
    }
  });
  drawPixelTile(ctx, TILE_INDEX.TNT_TOP, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const fuse = x >= 7 && x <= 8 && y >= 7 && y <= 8;
        px(x, y, fuse ? '#222222' : '#C92D24');
      }
    }
  });
  drawPixelTile(ctx, TILE_INDEX.TNT_BOTTOM, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        px(x, y, '#A8241D');
      }
    }
  });

  // 30. NEON_CYAN (Seoul Cyber Neon)
  drawPixelTile(ctx, TILE_INDEX.NEON_CYAN, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const border = x === 0 || x === 15 || y === 0 || y === 15;
        const innerRing = x === 2 || x === 13 || y === 2 || y === 13;
        if (border) px(x, y, '#14384E');
        else if (innerRing) px(x, y, '#99FFFF');
        else px(x, y, shade('#22E6E2', Math.floor((hash2(x, y, 301) - 0.5) * 18)));
      }
    }
  });

  // 31. NEON_MAGENTA (K-Pop Pink Neon)
  drawPixelTile(ctx, TILE_INDEX.NEON_MAGENTA, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const border = x === 0 || x === 15 || y === 0 || y === 15;
        const innerRing = x === 2 || x === 13 || y === 2 || y === 13;
        if (border) px(x, y, '#3D1536');
        else if (innerRing) px(x, y, '#FFC4EA');
        else px(x, y, shade('#FF4DB8', Math.floor((hash2(x, y, 302) - 0.5) * 18)));
      }
    }
  });

  // 32. BASALT (Jeju Volcanic Dark Columnar Stone)
  drawPixelTile(ctx, TILE_INDEX.BASALT, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const r = hash2(x, y, 303);
        const pore = r > 0.88;
        px(x, y, pore ? '#1C2026' : shade('#363C47', Math.floor((r - 0.5) * 20)));
      }
    }
  });

  // 33. GOLD_BLOCK (Royal Joseon Gold Block)
  drawPixelTile(ctx, TILE_INDEX.GOLD_BLOCK, (px) => {
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const border = x === 0 || x === 15 || y === 0 || y === 15;
        const diag = (x + y) % 7 === 0;
        if (border) px(x, y, '#B88418');
        else if (diag) px(x, y, '#FFF2A6');
        else px(x, y, shade('#F5C438', Math.floor((hash2(x, y, 304) - 0.5) * 20)));
      }
    }
  });

  const atlasTexture = new THREE.CanvasTexture(atlasCanvas);
  atlasTexture.colorSpace = THREE.SRGBColorSpace;
  atlasTexture.magFilter = THREE.NearestFilter;
  atlasTexture.minFilter = THREE.NearestFilter;
  atlasTexture.generateMipmaps = false;
  atlasTexture.needsUpdate = true;

  const opaqueMaterial = new THREE.MeshLambertMaterial({
    map: atlasTexture,
    vertexColors: true,
  });

  const translucentMaterial = new THREE.MeshLambertMaterial({
    map: atlasTexture,
    vertexColors: true,
    transparent: true,
    opacity: 0.72,
    depthWrite: false,
    side: THREE.DoubleSide,
  });

  const getFaceTile = (blockId: BlockId, faceDir: 'top' | 'bottom' | 'side'): number => {
    switch (blockId) {
      case BLOCK_IDS.GRASS:
        return faceDir === 'top'
          ? TILE_INDEX.GRASS_TOP
          : faceDir === 'bottom'
          ? TILE_INDEX.DIRT
          : TILE_INDEX.GRASS_SIDE;
      case BLOCK_IDS.DIRT:
        return TILE_INDEX.DIRT;
      case BLOCK_IDS.STONE:
        return TILE_INDEX.STONE;
      case BLOCK_IDS.COBBLESTONE:
        return TILE_INDEX.COBBLESTONE;
      case BLOCK_IDS.OAK_LOG:
        return faceDir === 'side' ? TILE_INDEX.OAK_LOG_SIDE : TILE_INDEX.OAK_LOG_TOP;
      case BLOCK_IDS.OAK_PLANKS:
        return TILE_INDEX.OAK_PLANKS;
      case BLOCK_IDS.OAK_LEAVES:
        return TILE_INDEX.OAK_LEAVES;
      case BLOCK_IDS.CHERRY_LEAVES:
        return TILE_INDEX.CHERRY_LEAVES;
      case BLOCK_IDS.SAND:
        return TILE_INDEX.SAND;
      case BLOCK_IDS.WATER:
        return TILE_INDEX.WATER;
      case BLOCK_IDS.COAL_ORE:
        return TILE_INDEX.COAL_ORE;
      case BLOCK_IDS.IRON_ORE:
        return TILE_INDEX.IRON_ORE;
      case BLOCK_IDS.GOLD_ORE:
        return TILE_INDEX.GOLD_ORE;
      case BLOCK_IDS.DIAMOND_ORE:
        return TILE_INDEX.DIAMOND_ORE;
      case BLOCK_IDS.HANOK_TILE:
        return faceDir === 'side' ? TILE_INDEX.HANOK_TILE_SIDE : TILE_INDEX.HANOK_TILE_TOP;
      case BLOCK_IDS.HANJI_WALL:
        return TILE_INDEX.HANJI_WALL;
      case BLOCK_IDS.RED_PILLAR:
        return faceDir === 'side' ? TILE_INDEX.RED_PILLAR_SIDE : TILE_INDEX.RED_PILLAR_TOP;
      case BLOCK_IDS.LANTERN:
        return faceDir === 'side' ? TILE_INDEX.LANTERN_SIDE : TILE_INDEX.LANTERN_TOP;
      case BLOCK_IDS.GLASS:
        return TILE_INDEX.GLASS;
      case BLOCK_IDS.BRICK:
        return TILE_INDEX.BRICK;
      case BLOCK_IDS.CRAFTING_TABLE:
        return faceDir === 'top'
          ? TILE_INDEX.CRAFT_TOP
          : faceDir === 'bottom'
          ? TILE_INDEX.OAK_PLANKS
          : TILE_INDEX.CRAFT_SIDE;
      case BLOCK_IDS.TNT:
        return faceDir === 'top'
          ? TILE_INDEX.TNT_TOP
          : faceDir === 'bottom'
          ? TILE_INDEX.TNT_BOTTOM
          : TILE_INDEX.TNT_SIDE;
      case BLOCK_IDS.NEON_CYAN:
        return TILE_INDEX.NEON_CYAN;
      case BLOCK_IDS.NEON_MAGENTA:
        return TILE_INDEX.NEON_MAGENTA;
      case BLOCK_IDS.BASALT:
        return TILE_INDEX.BASALT;
      case BLOCK_IDS.GOLD_BLOCK:
        return TILE_INDEX.GOLD_BLOCK;
      default:
        return TILE_INDEX.STONE;
    }
  };

  const getTileUV = (tileIdx: number) => {
    const col = tileIdx % ATLAS_COLS;
    const row = Math.floor(tileIdx / ATLAS_COLS);
    const pad = 0.0015;
    const u0 = col / ATLAS_COLS + pad;
    const u1 = (col + 1) / ATLAS_COLS - pad;
    // Canvas y=0 is top (v=1 in Three.js UV!)
    const v1 = 1 - row / ATLAS_ROWS - pad;
    const v0 = 1 - (row + 1) / ATLAS_ROWS + pad;
    return { u0, v0, u1, v1 };
  };

  // Cache single-block materials for dropped pickups & held items
  const singleBlockMatCache = new Map<number, THREE.Material[]>();
  const extractTileMat = (tileIdx: number, isTrans: boolean) => {
    const c = document.createElement('canvas');
    c.width = TILE_SIZE;
    c.height = TILE_SIZE;
    const cctx = c.getContext('2d')!;
    const col = tileIdx % ATLAS_COLS;
    const row = Math.floor(tileIdx / ATLAS_COLS);
    cctx.drawImage(
      atlasCanvas,
      col * TILE_SIZE,
      row * TILE_SIZE,
      TILE_SIZE,
      TILE_SIZE,
      0,
      0,
      TILE_SIZE,
      TILE_SIZE
    );
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    return new THREE.MeshLambertMaterial({
      map: t,
      transparent: isTrans,
      opacity: isTrans ? 0.78 : 1,
    });
  };

  const getSingleBlockMaterials = (blockId: number): THREE.Material[] => {
    if (singleBlockMatCache.has(blockId)) return singleBlockMatCache.get(blockId)!;
    const b = blockId as BlockId;
    const isTrans = b === BLOCK_IDS.WATER || b === BLOCK_IDS.GLASS;
    const sideMat = extractTileMat(getFaceTile(b, 'side'), isTrans);
    const topMat = extractTileMat(getFaceTile(b, 'top'), isTrans);
    const botMat = extractTileMat(getFaceTile(b, 'bottom'), isTrans);
    const mats = [sideMat, sideMat, topMat, botMat, sideMat, sideMat];
    singleBlockMatCache.set(blockId, mats);
    return mats;
  };

  const itemIconUrls = generateAllItemIcons(atlasCanvas, getFaceTile);

  cachedSystem = {
    atlasTexture,
    opaqueMaterial,
    translucentMaterial,
    getFaceTile,
    getTileUV,
    getSingleBlockMaterials,
    itemIconUrls,
  };
  return cachedSystem;
}

function generateAllItemIcons(
  atlasCanvas: HTMLCanvasElement,
  getFaceTile: (b: BlockId, dir: 'top' | 'bottom' | 'side') => number
): Record<string, string> {
  const urls: Record<string, string> = {};

  // Isometric 3D block icon renderer for all blocks 1..26!
  for (let b = 1; b <= 26; b++) {
    const c = document.createElement('canvas');
    c.width = 64;
    c.height = 64;
    const ctx = c.getContext('2d')!;
    ctx.imageSmoothingEnabled = false;

    const topIdx = getFaceTile(b as BlockId, 'top');
    const sideIdx = getFaceTile(b as BlockId, 'side');

    const drawSubTile = (tileIdx: number) => {
      const sub = document.createElement('canvas');
      sub.width = TILE_SIZE;
      sub.height = TILE_SIZE;
      sub
        .getContext('2d')!
        .drawImage(
          atlasCanvas,
          (tileIdx % ATLAS_COLS) * TILE_SIZE,
          Math.floor(tileIdx / ATLAS_COLS) * TILE_SIZE,
          TILE_SIZE,
          TILE_SIZE,
          0,
          0,
          TILE_SIZE,
          TILE_SIZE
        );
      return sub;
    };

    const topImg = drawSubTile(topIdx);
    const sideImg = drawSubTile(sideIdx);

    // Isometric top diamond
    ctx.save();
    ctx.translate(32, 8);
    ctx.transform(0.75, 0.38, -0.75, 0.38, 0, 0);
    ctx.drawImage(topImg, 0, 0, 32, 32);
    ctx.restore();

    // Left isometric face
    ctx.save();
    ctx.translate(8, 20);
    ctx.transform(0.75, 0.38, 0, 0.85, 0, 0);
    ctx.drawImage(sideImg, 0, 0, 32, 32);
    ctx.fillStyle = 'rgba(0,0,0,0.16)';
    ctx.fillRect(0, 0, 32, 32);
    ctx.restore();

    // Right isometric face
    ctx.save();
    ctx.translate(32, 32.2);
    ctx.transform(0.75, -0.38, 0, 0.85, 0, 0);
    ctx.drawImage(sideImg, 0, 0, 32, 32);
    ctx.fillStyle = 'rgba(0,0,0,0.32)';
    ctx.fillRect(0, 0, 32, 32);
    ctx.restore();

    urls[String(b)] = c.toDataURL('image/png');
  }

  // Hand-drawn crisp 64x64 icons for Tools, Korean Foods & Ingots!
  const makeCustomIcon = (draw: (ctx: CanvasRenderingContext2D) => void) => {
    const c = document.createElement('canvas');
    c.width = 64;
    c.height = 64;
    const ctx = c.getContext('2d')!;
    draw(ctx);
    return c.toDataURL('image/png');
  };

  urls['diamond_pickaxe'] = makeCustomIcon((ctx) => {
    ctx.strokeStyle = '#7C5333';
    ctx.lineWidth = 6;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(14, 52);
    ctx.lineTo(44, 22);
    ctx.stroke();

    ctx.strokeStyle = '#32E6DF';
    ctx.lineWidth = 7;
    ctx.beginPath();
    ctx.arc(38, 26, 20, -Math.PI * 0.82, -Math.PI * 0.05);
    ctx.stroke();
    ctx.strokeStyle = '#B8FFFF';
    ctx.lineWidth = 2.5;
    ctx.stroke();
  });

  urls['iron_axe'] = makeCustomIcon((ctx) => {
    ctx.strokeStyle = '#7C5333';
    ctx.lineWidth = 6;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(14, 52);
    ctx.lineTo(46, 18);
    ctx.stroke();

    ctx.fillStyle = '#DCE3EC';
    ctx.beginPath();
    ctx.moveTo(42, 14);
    ctx.quadraticCurveTo(22, 12, 22, 30);
    ctx.lineTo(36, 32);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = '#FFFFFF';
    ctx.lineWidth = 2;
    ctx.stroke();
  });

  urls['joseon_sword'] = makeCustomIcon((ctx) => {
    // Korean Hwandudaedo Ring-Pommel Royal Sword!
    ctx.strokeStyle = '#E8B94F';
    ctx.lineWidth = 3.5;
    ctx.beginPath();
    ctx.arc(13, 51, 5, 0, Math.PI * 2);
    ctx.stroke();

    ctx.strokeStyle = '#9E2432';
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(17, 47);
    ctx.lineTo(25, 39);
    ctx.stroke();

    ctx.strokeStyle = '#EEF4FF';
    ctx.lineWidth = 5.5;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(26, 38);
    ctx.lineTo(53, 11);
    ctx.stroke();

    ctx.strokeStyle = '#E8B94F';
    ctx.lineWidth = 4.5;
    ctx.beginPath();
    ctx.moveTo(20, 33);
    ctx.lineTo(31, 44);
    ctx.stroke();
  });

  urls['kimbap'] = makeCustomIcon((ctx) => {
    // Korean Kimbap slice (김밥) showing seaweed, white rice, egg, carrot, spinach!
    ctx.fillStyle = '#1C261E';
    ctx.beginPath();
    ctx.arc(32, 32, 22, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#FAF8F5';
    ctx.beginPath();
    ctx.arc(32, 32, 17, 0, Math.PI * 2);
    ctx.fill();
    // Colorful fillings
    ctx.fillStyle = '#FFD152';
    ctx.fillRect(24, 24, 8, 8);
    ctx.fillStyle = '#F26B3A';
    ctx.fillRect(32, 24, 8, 8);
    ctx.fillStyle = '#4CA64C';
    ctx.fillRect(24, 32, 8, 8);
    ctx.fillStyle = '#C95A49';
    ctx.fillRect(32, 32, 8, 8);
  });

  urls['tteokbokki'] = makeCustomIcon((ctx) => {
    // Spicy Korean Tteokbokki bowl (떡볶이)!
    ctx.fillStyle = '#E0422D';
    ctx.beginPath();
    ctx.ellipse(32, 30, 22, 12, 0, 0, Math.PI * 2);
    ctx.fill();
    // Rice cakes
    ctx.strokeStyle = '#FFF5EB';
    ctx.lineWidth = 6;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(20, 28);
    ctx.lineTo(32, 25);
    ctx.moveTo(28, 33);
    ctx.lineTo(42, 29);
    ctx.stroke();
    // Bowl base
    ctx.fillStyle = '#2B3547';
    ctx.beginPath();
    ctx.moveTo(10, 31);
    ctx.quadraticCurveTo(32, 54, 54, 31);
    ctx.closePath();
    ctx.fill();
  });

  const makeGemOrIngot = (id: InventoryItemId, main: string, shine: string, round: boolean) => {
    urls[String(id)] = makeCustomIcon((ctx) => {
      ctx.fillStyle = main;
      ctx.beginPath();
      if (round) {
        ctx.moveTo(32, 10);
        ctx.lineTo(50, 28);
        ctx.lineTo(32, 52);
        ctx.lineTo(14, 28);
      } else {
        ctx.roundRect(14, 20, 36, 24, 6);
      }
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = shine;
      ctx.beginPath();
      ctx.arc(27, 26, 5, 0, Math.PI * 2);
      ctx.fill();
    });
  };

  makeGemOrIngot('coal', '#2B2E36', '#555A66', true);
  makeGemOrIngot('iron_ingot', '#D8E0EA', '#FFFFFF', false);
  makeGemOrIngot('gold_ingot', '#F5C438', '#FFF4A3', false);
  makeGemOrIngot('diamond', '#32E6DF', '#C9FFFF', true);

  urls['bingsoo'] = makeCustomIcon((ctx) => {
    // Strawberry Bingsu shaved ice dessert!
    ctx.fillStyle = '#FFF7FA';
    ctx.beginPath();
    ctx.arc(32, 28, 17, Math.PI, 0);
    ctx.fill();
    ctx.fillStyle = '#FF5C8D';
    ctx.beginPath();
    ctx.arc(26, 22, 5, 0, Math.PI * 2);
    ctx.arc(38, 23, 5, 0, Math.PI * 2);
    ctx.arc(32, 16, 5.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#48C4D8';
    ctx.beginPath();
    ctx.moveTo(12, 28);
    ctx.quadraticCurveTo(32, 52, 52, 28);
    ctx.closePath();
    ctx.fill();
  });

  urls['honey_tteok'] = makeCustomIcon((ctx) => {
    // Pastel Korean Honey Rice Cakes (꿀떡)!
    ctx.fillStyle = '#5C3D28';
    ctx.beginPath();
    ctx.ellipse(32, 42, 22, 8, 0, 0, Math.PI * 2);
    ctx.fill();
    const cakes = [
      { x: 22, y: 34, c: '#FFB3C6' },
      { x: 40, y: 34, c: '#B8E8B0' },
      { x: 31, y: 26, c: '#FFF5E1' },
    ];
    for (const k of cakes) {
      ctx.fillStyle = k.c;
      ctx.beginPath();
      ctx.ellipse(k.x, k.y, 9, 6.5, 0, 0, Math.PI * 2);
      ctx.fill();
    }
  });

  return urls;
}
