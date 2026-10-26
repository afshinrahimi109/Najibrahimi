import * as THREE from 'three';
import { BLOCK_IDS } from '../data/items';
import { BlockId } from '../types/game';
import { BlockTextureSystem } from './BlockTextures';

export const CHUNK_SIZE = 16;
export const WORLD_HEIGHT = 64;
export const CHUNKS_X = 6;
export const CHUNKS_Z = 6;
export const WORLD_WIDTH = CHUNKS_X * CHUNK_SIZE; // 96
export const WORLD_DEPTH = CHUNKS_Z * CHUNK_SIZE; // 96
export const WATER_LEVEL = 14;

export interface RaycastHit {
  bx: number;
  by: number;
  bz: number;
  nx: number;
  ny: number;
  nz: number;
  blockId: BlockId;
  distance: number;
}

interface ChunkMeshPair {
  opaque: THREE.Mesh | null;
  translucent: THREE.Mesh | null;
}

function hash2D(x: number, z: number, seed = 1337): number {
  let n = Math.imul(x * 374761393 + z * 668265263 + seed * 1442695041, 1274126177);
  n = (n ^ (n >>> 13)) >>> 0;
  return (n & 0xffff) / 0xffff;
}

function smoothNoise2D(x: number, z: number, seed = 1337): number {
  const ix = Math.floor(x);
  const iz = Math.floor(z);
  const fx = x - ix;
  const fz = z - iz;
  const u = fx * fx * (3 - 2 * fx);
  const v = fz * fz * (3 - 2 * fz);

  const a = hash2D(ix, iz, seed);
  const b = hash2D(ix + 1, iz, seed);
  const c = hash2D(ix, iz + 1, seed);
  const d = hash2D(ix + 1, iz + 1, seed);

  return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v;
}

function fbm2D(x: number, z: number): number {
  return (
    smoothNoise2D(x * 0.045, z * 0.045, 101) * 0.6 +
    smoothNoise2D(x * 0.1, z * 0.1, 202) * 0.28 +
    smoothNoise2D(x * 0.22, z * 0.22, 303) * 0.12
  );
}

const FACE_DEFS = [
  {
    // +X
    dir: [1, 0, 0] as const,
    faceType: 'side' as const,
    shade: 0.74,
    corners: [
      [1, 0, 1],
      [1, 0, 0],
      [1, 1, 0],
      [1, 1, 1],
    ],
  },
  {
    // -X
    dir: [-1, 0, 0] as const,
    faceType: 'side' as const,
    shade: 0.74,
    corners: [
      [0, 0, 0],
      [0, 0, 1],
      [0, 1, 1],
      [0, 1, 0],
    ],
  },
  {
    // +Y (Top)
    dir: [0, 1, 0] as const,
    faceType: 'top' as const,
    shade: 1.0,
    corners: [
      [0, 1, 1],
      [1, 1, 1],
      [1, 1, 0],
      [0, 1, 0],
    ],
  },
  {
    // -Y (Bottom)
    dir: [0, -1, 0] as const,
    faceType: 'bottom' as const,
    shade: 0.54,
    corners: [
      [0, 0, 0],
      [1, 0, 0],
      [1, 0, 1],
      [0, 0, 1],
    ],
  },
  {
    // +Z
    dir: [0, 0, 1] as const,
    faceType: 'side' as const,
    shade: 0.86,
    corners: [
      [0, 0, 1],
      [1, 0, 1],
      [1, 1, 1],
      [0, 1, 1],
    ],
  },
  {
    // -Z
    dir: [0, 0, -1] as const,
    faceType: 'side' as const,
    shade: 0.82,
    corners: [
      [1, 0, 0],
      [0, 0, 0],
      [0, 1, 0],
      [1, 1, 0],
    ],
  },
];

export class VoxelWorld {
  public readonly data: Uint8Array;
  public readonly worldGroup: THREE.Group;
  private readonly texSys: BlockTextureSystem;
  private readonly chunkMeshes: Map<string, ChunkMeshPair> = new Map();

  constructor(texSys: BlockTextureSystem) {
    this.texSys = texSys;
    this.data = new Uint8Array(WORLD_WIDTH * WORLD_HEIGHT * WORLD_DEPTH);
    this.worldGroup = new THREE.Group();
    this.generateTerrainAndKoreanVillage();
    this.rebuildAllChunks();
  }

  private idx(x: number, y: number, z: number): number {
    return (y * WORLD_DEPTH + z) * WORLD_WIDTH + x;
  }

  public inBounds(x: number, y: number, z: number): boolean {
    return (
      x >= 0 &&
      x < WORLD_WIDTH &&
      y >= 0 &&
      y < WORLD_HEIGHT &&
      z >= 0 &&
      z < WORLD_DEPTH
    );
  }

  public getBlock(x: number, y: number, z: number): BlockId {
    if (!this.inBounds(x, y, z)) return BLOCK_IDS.AIR;
    return this.data[this.idx(x, y, z)] as BlockId;
  }

  public setBlockRaw(x: number, y: number, z: number, block: BlockId): void {
    if (!this.inBounds(x, y, z)) return;
    this.data[this.idx(x, y, z)] = block;
  }

  public setBlock(x: number, y: number, z: number, block: BlockId): void {
    if (!this.inBounds(x, y, z)) return;
    // Prevent breaking bottom bedrock floor y=0
    if (y === 0 && block === BLOCK_IDS.AIR) return;
    this.data[this.idx(x, y, z)] = block;

    const cx = Math.floor(x / CHUNK_SIZE);
    const cz = Math.floor(z / CHUNK_SIZE);
    this.rebuildChunk(cx, cz);

    const lx = x % CHUNK_SIZE;
    const lz = z % CHUNK_SIZE;
    if (lx === 0 && cx > 0) this.rebuildChunk(cx - 1, cz);
    if (lx === CHUNK_SIZE - 1 && cx < CHUNKS_X - 1) this.rebuildChunk(cx + 1, cz);
    if (lz === 0 && cz > 0) this.rebuildChunk(cx, cz - 1);
    if (lz === CHUNK_SIZE - 1 && cz < CHUNKS_Z - 1) this.rebuildChunk(cx, cz + 1);
  }

  public isSolid(x: number, y: number, z: number): boolean {
    if (x < 0 || x >= WORLD_WIDTH || z < 0 || z >= WORLD_DEPTH) return true; // invisible world border keeps player in world
    if (y < 0) return true;
    if (y >= WORLD_HEIGHT) return false;
    const b = this.getBlock(x, y, z);
    return b !== BLOCK_IDS.AIR && b !== BLOCK_IDS.WATER;
  }

  public isTranslucent(b: BlockId): boolean {
    return b === BLOCK_IDS.WATER || b === BLOCK_IDS.GLASS;
  }

  public getSurfaceY(x: number, z: number): number {
    const bx = Math.max(0, Math.min(WORLD_WIDTH - 1, Math.floor(x)));
    const bz = Math.max(0, Math.min(WORLD_DEPTH - 1, Math.floor(z)));
    for (let y = WORLD_HEIGHT - 1; y >= 1; y--) {
      const b = this.getBlock(bx, y, bz);
      if (
        b !== BLOCK_IDS.AIR &&
        b !== BLOCK_IDS.WATER &&
        b !== BLOCK_IDS.OAK_LEAVES &&
        b !== BLOCK_IDS.CHERRY_LEAVES
      ) {
        return y + 1;
      }
    }
    return 17;
  }

  private generateTerrainAndKoreanVillage(): void {
    const villageX = 48;
    const villageZ = 46;
    const villageGround = 16;

    // 1. Base Terrain, Pond, Ore Mountain & Underground Ores
    for (let z = 0; z < WORLD_DEPTH; z++) {
      for (let x = 0; x < WORLD_WIDTH; x++) {
        const n = fbm2D(x, z);
        let h = Math.floor(13 + n * 13);

        // Mountain in NE quadrant (x: 66..88, z: 12..34) for mining ores & cave!
        const distMountain = Math.hypot(x - 76, z - 22);
        if (distMountain < 18) {
          h += Math.floor((1 - distMountain / 18) * 14);
        }

        // Scenic pond south of village (x: 40..56, z: 58..70)
        const distPond = Math.hypot((x - 48) * 0.85, (z - 64) * 1.15);
        if (distPond < 9.5) {
          h = Math.floor(11 + (distPond / 9.5) * 3);
        } else {
          // Flatten central Korean Hanok Village plaza smoothly
          const distVillage = Math.hypot(x - villageX, z - villageZ);
          if (distVillage < 17) {
            h = villageGround;
          } else if (distVillage < 25) {
            const t = (distVillage - 17) / 8;
            h = Math.round(villageGround * (1 - t) + h * t);
          }
        }

        h = Math.max(4, Math.min(WORLD_HEIGHT - 8, h));

        for (let y = 0; y <= h; y++) {
          if (y === 0) {
            this.setBlockRaw(x, y, z, BLOCK_IDS.STONE);
          } else if (y === h) {
            if (h <= WATER_LEVEL + 1 && distPond < 11.5) {
              this.setBlockRaw(x, y, z, BLOCK_IDS.SAND);
            } else if (h > 25) {
              this.setBlockRaw(x, y, z, BLOCK_IDS.STONE);
            } else {
              this.setBlockRaw(x, y, z, BLOCK_IDS.GRASS);
            }
          } else if (y >= h - 3) {
            this.setBlockRaw(x, y, z, BLOCK_IDS.DIRT);
          } else {
            // Underground Stone + Rich Minecraft Ore Veins!
            const oreRoll = hash2D(x * 7 + y * 13, z * 11 + y * 5, 999);
            let ore: BlockId = BLOCK_IDS.STONE;
            if (y <= 10 && oreRoll > 0.972) ore = BLOCK_IDS.DIAMOND_ORE;
            else if (y <= 16 && oreRoll > 0.955) ore = BLOCK_IDS.GOLD_ORE;
            else if (y <= 22 && oreRoll > 0.928) ore = BLOCK_IDS.IRON_ORE;
            else if (oreRoll > 0.895) ore = BLOCK_IDS.COAL_ORE;
            this.setBlockRaw(x, y, z, ore);
          }
        }

        // Fill pond water up to WATER_LEVEL
        if (h < WATER_LEVEL) {
          for (let y = h + 1; y <= WATER_LEVEL; y++) {
            this.setBlockRaw(x, y, z, BLOCK_IDS.WATER);
          }
        }
      }
    }

    // 2. Carve Open Mining Cave Tunnel into NE Ore Mountain (entrance near x=67, z=26)
    for (let step = 0; step < 26; step++) {
      const cx = Math.round(65 + step * 0.55);
      const cz = Math.round(28 - step * 0.35 + Math.sin(step * 0.3) * 2);
      const cy = Math.max(6, Math.round(17 - step * 0.38));
      for (let dy = -1; dy <= 2; dy++) {
        for (let dz = -2; dz <= 2; dz++) {
          for (let dx = -2; dx <= 2; dx++) {
            if (dx * dx + dz * dz <= 5) {
              this.setBlockRaw(cx + dx, cy + dy, cz + dz, BLOCK_IDS.AIR);
            }
          }
        }
      }
      // Expose visible ores on cave walls & lanterns at entrance!
      if (step === 2) {
        this.setBlockRaw(cx - 2, cy + 2, cz, BLOCK_IDS.LANTERN);
      }
      if (step % 5 === 0) {
        this.setBlockRaw(cx + 2, cy + 1, cz + 2, step > 14 ? BLOCK_IDS.DIAMOND_ORE : BLOCK_IDS.IRON_ORE);
        this.setBlockRaw(cx - 2, cy, cz - 2, step > 10 ? BLOCK_IDS.GOLD_ORE : BLOCK_IDS.COAL_ORE);
      }
    }

    // 3. Stone Courtyard Pathways in Village Plaza
    for (let z = 39; z <= 57; z++) {
      for (let x = 46; x <= 50; x++) {
        this.setBlockRaw(x, villageGround, z, BLOCK_IDS.BRICK);
      }
    }
    for (let x = 36; x <= 60; x++) {
      for (let z = 46; z <= 49; z++) {
        this.setBlockRaw(x, villageGround, z, BLOCK_IDS.BRICK);
      }
    }

    // 4. Build Grand Korean Hanok Royal Pavilion (한옥 본당) at x: 42..54, z: 29..38
    this.buildGrandHanok(42, villageGround + 1, 29, 13, 9);

    // 5. Build Two Korean Market Stalls (전통 시장) on West & East of Plaza
    this.buildKoreanMarketStall(33, villageGround + 1, 44, true); // Grandma's Kimbap & Tteokbokki Stall
    this.buildKoreanMarketStall(59, villageGround + 1, 44, false); // Blacksmith & Architect Stall

    // 6. Build Arched Wooden Cherry-Blossom Bridge across Scenic Pond (x: 46..50, z: 58..70)
    for (let z = 58; z <= 70; z++) {
      const arch = z >= 61 && z <= 67 ? 1 : 0;
      const by = WATER_LEVEL + 1 + arch;
      for (let x = 46; x <= 50; x++) {
        this.setBlockRaw(x, by, z, BLOCK_IDS.OAK_PLANKS);
        if (x === 46 || x === 50) {
          this.setBlockRaw(x, by + 1, z, BLOCK_IDS.RED_PILLAR);
          if (z === 59 || z === 64 || z === 69) {
            this.setBlockRaw(x, by + 2, z, BLOCK_IDS.LANTERN);
          }
        }
      }
    }

    // 7. Street Cheongsachorong Lantern Posts around Plaza
    const lanternPosts = [
      [44, 42],
      [52, 42],
      [44, 53],
      [52, 53],
    ];
    for (const [lx, lz] of lanternPosts) {
      this.setBlockRaw(lx, villageGround + 1, lz, BLOCK_IDS.RED_PILLAR);
      this.setBlockRaw(lx, villageGround + 2, lz, BLOCK_IDS.RED_PILLAR);
      this.setBlockRaw(lx, villageGround + 3, lz, BLOCK_IDS.RED_PILLAR);
      this.setBlockRaw(lx, villageGround + 4, lz, BLOCK_IDS.LANTERN);
    }

    // 8. Plant Pink Korean Cherry Blossom Trees (벚꽃 나무) & Oak Trees!
    const cherrySpots = [
      [37, 56],
      [59, 56],
      [35, 35],
      [61, 35],
      [38, 66],
      [58, 66],
      [27, 48],
      [68, 48],
    ];
    for (const [tx, tz] of cherrySpots) {
      const ty = this.getSurfaceY(tx, tz);
      if (this.getBlock(tx, ty - 1, tz) === BLOCK_IDS.GRASS) {
        this.plantTree(tx, ty, tz, true);
      }
    }

    // Scatter natural Oak & Cherry trees in outer meadows
    for (let z = 8; z < WORLD_DEPTH - 8; z += 7) {
      for (let x = 8; x < WORLD_WIDTH - 8; x += 7) {
        const jx = x + Math.floor(hash2D(x, z, 701) * 4);
        const jz = z + Math.floor(hash2D(x, z, 702) * 4);
        const distCenter = Math.hypot(jx - villageX, jz - villageZ);
        const distCave = Math.hypot(jx - 67, jz - 27);
        if (distCenter < 24 || distCave < 8) continue;
        if (hash2D(jx, jz, 703) > 0.42) {
          const sy = this.getSurfaceY(jx, jz);
          if (this.getBlock(jx, sy - 1, jz) === BLOCK_IDS.GRASS && sy < 27) {
            const isCherry = hash2D(jx, jz, 704) > 0.55;
            this.plantTree(jx, sy, jz, isCherry);
          }
        }
      }
    }
  }

  private buildGrandHanok(
    x0: number,
    y0: number,
    z0: number,
    w: number,
    d: number
  ): void {
    // 1. Raised Stone Palace Terrace (기단)
    for (let z = z0 - 1; z <= z0 + d; z++) {
      for (let x = x0 - 1; x <= x0 + w; x++) {
        this.setBlockRaw(x, y0 - 1, z, BLOCK_IDS.BRICK);
        this.setBlockRaw(x, y0, z, BLOCK_IDS.BRICK);
      }
    }
    // Warm Oak Plank Floor inside
    for (let z = z0 + 1; z < z0 + d - 1; z++) {
      for (let x = x0 + 1; x < x0 + w - 1; x++) {
        this.setBlockRaw(x, y0, z, BLOCK_IDS.OAK_PLANKS);
      }
    }
    // Front stone stairs at z = z0 + d + 1
    const midX = x0 + Math.floor(w / 2);
    for (let sx = midX - 1; sx <= midX + 1; sx++) {
      this.setBlockRaw(sx, y0, z0 + d + 1, BLOCK_IDS.BRICK);
    }

    // 2. Red Dancheong Pillars & Hanji Paper Lattice Walls (height 4: y0+1..y0+4)
    for (let wy = y0 + 1; wy <= y0 + 4; wy++) {
      for (let z = z0; z < z0 + d; z++) {
        for (let x = x0; x < x0 + w; x++) {
          const onEdgeX = x === x0 || x === x0 + w - 1;
          const onEdgeZ = z === z0 || z === z0 + d - 1;
          if (!onEdgeX && !onEdgeZ) continue;

          // Front wide open entrance
          const isFrontDoor = z === z0 + d - 1 && Math.abs(x - midX) <= 1 && wy <= y0 + 3;
          if (isFrontDoor) continue;

          const isPillar =
            (onEdgeX && onEdgeZ) ||
            x === midX - 2 ||
            x === midX + 2 ||
            z === z0 + Math.floor(d / 2);

          this.setBlockRaw(
            x,
            wy,
            z,
            isPillar ? BLOCK_IDS.RED_PILLAR : BLOCK_IDS.HANJI_WALL
          );
        }
      }
    }

    // Interior Crafting Table & Glowing Korean Lanterns!
    this.setBlockRaw(midX, y0 + 1, z0 + 2, BLOCK_IDS.CRAFTING_TABLE);
    this.setBlockRaw(x0 + 2, y0 + 4, z0 + 2, BLOCK_IDS.LANTERN);
    this.setBlockRaw(x0 + w - 3, y0 + 4, z0 + 2, BLOCK_IDS.LANTERN);
    this.setBlockRaw(midX - 2, y0 + 3, z0 + d, BLOCK_IDS.LANTERN);
    this.setBlockRaw(midX + 2, y0 + 3, z0 + d, BLOCK_IDS.LANTERN);

    // 3. Multi-tiered Pitched Korean Giwa (기와) Roof with Upturned Corner Eaves!
    for (let layer = 0; layer < 4; layer++) {
      const ry = y0 + 5 + layer;
      const rx0 = x0 - 2 + layer;
      const rx1 = x0 + w + 1 - layer;
      const rz0 = z0 - 2 + layer;
      const rz1 = z0 + d + 1 - layer;
      for (let z = rz0; z <= rz1; z++) {
        for (let x = rx0; x <= rx1; x++) {
          this.setBlockRaw(x, ry, z, BLOCK_IDS.HANOK_TILE);
        }
      }
      // Iconic Korean upturned roof corners (처마 곡선) on bottom eave!
      if (layer === 0) {
        this.setBlockRaw(rx0, ry + 1, rz0, BLOCK_IDS.HANOK_TILE);
        this.setBlockRaw(rx1, ry + 1, rz0, BLOCK_IDS.HANOK_TILE);
        this.setBlockRaw(rx0, ry + 1, rz1, BLOCK_IDS.HANOK_TILE);
        this.setBlockRaw(rx1, ry + 1, rz1, BLOCK_IDS.HANOK_TILE);
      }
    }
  }

  private buildKoreanMarketStall(
    x0: number,
    y0: number,
    z0: number,
    facingEast: boolean
  ): void {
    // 5x6 cozy wooden stall with Hanok tile awning & glowing lanterns
    for (let z = z0; z < z0 + 6; z++) {
      for (let x = x0; x < x0 + 4; x++) {
        this.setBlockRaw(x, y0 - 1, z, BLOCK_IDS.OAK_PLANKS);
      }
    }
    // Corner posts
    for (const [px, pz] of [
      [x0, z0],
      [x0 + 3, z0],
      [x0, z0 + 5],
      [x0 + 3, z0 + 5],
    ]) {
      for (let py = y0; py <= y0 + 2; py++) {
        this.setBlockRaw(px, py, pz, BLOCK_IDS.OAK_LOG);
      }
    }
    // Counter front
    const counterX = facingEast ? x0 + 3 : x0;
    for (let z = z0 + 1; z <= z0 + 4; z++) {
      this.setBlockRaw(counterX, y0, z, BLOCK_IDS.OAK_PLANKS);
    }
    this.setBlockRaw(facingEast ? x0 + 1 : x0 + 2, y0, z0 + 2, BLOCK_IDS.CRAFTING_TABLE);

    // Sloped Hanok Tile Canopy + Hanging Lanterns
    for (let z = z0 - 1; z <= z0 + 6; z++) {
      for (let x = x0 - 1; x <= x0 + 4; x++) {
        this.setBlockRaw(x, y0 + 3, z, BLOCK_IDS.HANOK_TILE);
      }
    }
    this.setBlockRaw(counterX, y0 + 2, z0, BLOCK_IDS.LANTERN);
    this.setBlockRaw(counterX, y0 + 2, z0 + 5, BLOCK_IDS.LANTERN);
  }

  private plantTree(x: number, y: number, z: number, isCherry: boolean): void {
    const trunkH = isCherry ? 5 : 4;
    const leafBlock = isCherry ? BLOCK_IDS.CHERRY_LEAVES : BLOCK_IDS.OAK_LEAVES;

    for (let ty = 0; ty < trunkH; ty++) {
      this.setBlockRaw(x, y + ty, z, BLOCK_IDS.OAK_LOG);
    }

    const crownBase = y + trunkH - 2;
    for (let ly = 0; ly <= 3; ly++) {
      const radius = ly === 3 ? 1 : ly === 0 ? 2 : isCherry ? 3 : 2;
      for (let dz = -radius; dz <= radius; dz++) {
        for (let dx = -radius; dx <= radius; dx++) {
          if (Math.abs(dx) === radius && Math.abs(dz) === radius && ly !== 1) continue;
          if (dx === 0 && dz === 0 && ly < 2) continue;
          const bx = x + dx;
          const by = crownBase + ly;
          const bz = z + dz;
          if (this.getBlock(bx, by, bz) === BLOCK_IDS.AIR) {
            this.setBlockRaw(bx, by, bz, leafBlock);
          }
        }
      }
    }
  }

  public rebuildAllChunks(): void {
    for (let cz = 0; cz < CHUNKS_Z; cz++) {
      for (let cx = 0; cx < CHUNKS_X; cx++) {
        this.rebuildChunk(cx, cz);
      }
    }
  }

  public rebuildChunk(cx: number, cz: number): void {
    const key = `${cx}_${cz}`;
    const prev = this.chunkMeshes.get(key);
    if (prev) {
      if (prev.opaque) {
        this.worldGroup.remove(prev.opaque);
        prev.opaque.geometry.dispose();
      }
      if (prev.translucent) {
        this.worldGroup.remove(prev.translucent);
        prev.translucent.geometry.dispose();
      }
    }

    const opPos: number[] = [];
    const opNorm: number[] = [];
    const opUv: number[] = [];
    const opCol: number[] = [];
    const opIdx: number[] = [];

    const trPos: number[] = [];
    const trNorm: number[] = [];
    const trUv: number[] = [];
    const trCol: number[] = [];
    const trIdx: number[] = [];

    const startX = cx * CHUNK_SIZE;
    const startZ = cz * CHUNK_SIZE;

    const isOccluding = (x: number, y: number, z: number) => {
      if (!this.inBounds(x, y, z)) return false;
      const b = this.getBlock(x, y, z);
      return b !== BLOCK_IDS.AIR && !this.isTranslucent(b);
    };

    for (let y = 0; y < WORLD_HEIGHT; y++) {
      for (let z = startZ; z < startZ + CHUNK_SIZE; z++) {
        for (let x = startX; x < startX + CHUNK_SIZE; x++) {
          const block = this.getBlock(x, y, z);
          if (block === BLOCK_IDS.AIR) continue;

          const trans = this.isTranslucent(block);
          const posArr = trans ? trPos : opPos;
          const normArr = trans ? trNorm : opNorm;
          const uvArr = trans ? trUv : opUv;
          const colArr = trans ? trCol : opCol;
          const idxArr = trans ? trIdx : opIdx;

          const isSelfGlowing = block === BLOCK_IDS.LANTERN;

          for (const face of FACE_DEFS) {
            const [dx, dy, dz] = face.dir;
            const nx = x + dx;
            const ny = y + dy;
            const nz = z + dz;
            const neighbor = this.getBlock(nx, ny, nz);

            if (trans) {
              // Cull between identical translucent blocks or against opaque blocks
              if (neighbor === block || (neighbor !== BLOCK_IDS.AIR && !this.isTranslucent(neighbor))) {
                continue;
              }
            } else {
              if (neighbor !== BLOCK_IDS.AIR && !this.isTranslucent(neighbor)) {
                continue;
              }
            }

            const tile = this.texSys.getFaceTile(block, face.faceType);
            const { u0, v0, u1, v1 } = this.texSys.getTileUV(tile);
            const uvs: Array<[number, number]> = [
              [u0, v0],
              [u1, v0],
              [u1, v1],
              [u0, v1],
            ];

            // Water surface slightly lower on top for classic Minecraft shoreline look
            const waterDrop = block === BLOCK_IDS.WATER ? 0.12 : 0;

            const vBase = posArr.length / 3;
            for (let ci = 0; ci < 4; ci++) {
              const [cxOff, cyOff, czOff] = face.corners[ci];
              const vy = cyOff === 1 ? y + 1 - waterDrop : y;
              posArr.push(x + cxOff, vy, z + czOff);
              normArr.push(dx, dy, dz);
              uvArr.push(uvs[ci][0], uvs[ci][1]);

              // Smooth Minecraft Corner Ambient Occlusion!
              let ao = 1.0;
              if (!isSelfGlowing && !trans) {
                const sx = cxOff === 1 ? 1 : -1;
                const sy = cyOff === 1 ? 1 : -1;
                const sz = czOff === 1 ? 1 : -1;
                let occ = 0;
                if (dy !== 0) {
                  if (isOccluding(x + sx, y + dy, z)) occ++;
                  if (isOccluding(x, y + dy, z + sz)) occ++;
                  if (isOccluding(x + sx, y + dy, z + sz)) occ++;
                } else if (dx !== 0) {
                  if (isOccluding(x + dx, y + sy, z)) occ++;
                  if (isOccluding(x + dx, y, z + sz)) occ++;
                  if (isOccluding(x + dx, y + sy, z + sz)) occ++;
                } else {
                  if (isOccluding(x + sx, y + sy, z + dz)) occ++;
                  if (isOccluding(x + sx, y, z + dz)) occ++;
                  if (isOccluding(x, y + sy, z + dz)) occ++;
                }
                ao = 1.0 - occ * 0.145;
              }

              const brightness = isSelfGlowing ? 1.15 : face.shade * ao;
              colArr.push(brightness, brightness, brightness);
            }

            idxArr.push(vBase, vBase + 1, vBase + 2, vBase, vBase + 2, vBase + 3);
          }
        }
      }
    }

    const buildMesh = (
      pos: number[],
      norm: number[],
      uv: number[],
      col: number[],
      ind: number[],
      mat: THREE.Material
    ): THREE.Mesh | null => {
      if (pos.length === 0) return null;
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      geo.setAttribute('normal', new THREE.Float32BufferAttribute(norm, 3));
      geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
      geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
      geo.setIndex(ind);
      geo.computeBoundingSphere();
      const m = new THREE.Mesh(geo, mat);
      this.worldGroup.add(m);
      return m;
    };

    const opaque = buildMesh(opPos, opNorm, opUv, opCol, opIdx, this.texSys.opaqueMaterial);
    const translucent = buildMesh(
      trPos,
      trNorm,
      trUv,
      trCol,
      trIdx,
      this.texSys.translucentMaterial
    );

    this.chunkMeshes.set(key, { opaque, translucent });
  }

  /**
   * Fast Amanatides & Woo 3D DDA Voxel Raycast
   */
  public raycast(
    origin: THREE.Vector3,
    direction: THREE.Vector3,
    maxDistance = 6.2
  ): RaycastHit | null {
    const dir = direction.clone().normalize();
    let x = Math.floor(origin.x);
    let y = Math.floor(origin.y);
    let z = Math.floor(origin.z);

    const stepX = dir.x > 0 ? 1 : dir.x < 0 ? -1 : 0;
    const stepY = dir.y > 0 ? 1 : dir.y < 0 ? -1 : 0;
    const stepZ = dir.z > 0 ? 1 : dir.z < 0 ? -1 : 0;

    const tDeltaX = stepX !== 0 ? Math.abs(1 / dir.x) : Infinity;
    const tDeltaY = stepY !== 0 ? Math.abs(1 / dir.y) : Infinity;
    const tDeltaZ = stepZ !== 0 ? Math.abs(1 / dir.z) : Infinity;

    let tMaxX =
      stepX > 0
        ? (x + 1 - origin.x) * tDeltaX
        : stepX < 0
        ? (origin.x - x) * tDeltaX
        : Infinity;
    let tMaxY =
      stepY > 0
        ? (y + 1 - origin.y) * tDeltaY
        : stepY < 0
        ? (origin.y - y) * tDeltaY
        : Infinity;
    let tMaxZ =
      stepZ > 0
        ? (z + 1 - origin.z) * tDeltaZ
        : stepZ < 0
        ? (origin.z - z) * tDeltaZ
        : Infinity;

    let nx = 0;
    let ny = 0;
    let nz = 0;
    let dist = 0;

    for (let i = 0; i < 64; i++) {
      if (this.inBounds(x, y, z)) {
        const b = this.getBlock(x, y, z);
        if (b !== BLOCK_IDS.AIR && b !== BLOCK_IDS.WATER) {
          return {
            bx: x,
            by: y,
            bz: z,
            nx,
            ny,
            nz,
            blockId: b,
            distance: dist,
          };
        }
      }

      if (tMaxX < tMaxY) {
        if (tMaxX < tMaxZ) {
          dist = tMaxX;
          if (dist > maxDistance) break;
          x += stepX;
          tMaxX += tDeltaX;
          nx = -stepX;
          ny = 0;
          nz = 0;
        } else {
          dist = tMaxZ;
          if (dist > maxDistance) break;
          z += stepZ;
          tMaxZ += tDeltaZ;
          nx = 0;
          ny = 0;
          nz = -stepZ;
        }
      } else {
        if (tMaxY < tMaxZ) {
          dist = tMaxY;
          if (dist > maxDistance) break;
          y += stepY;
          tMaxY += tDeltaY;
          nx = 0;
          ny = -stepY;
          nz = 0;
        } else {
          dist = tMaxZ;
          if (dist > maxDistance) break;
          z += stepZ;
          tMaxZ += tDeltaZ;
          nx = 0;
          ny = 0;
          nz = -stepZ;
        }
      }
    }

    return null;
  }
}
