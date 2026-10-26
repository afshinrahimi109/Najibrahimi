import React, { useState } from 'react';
import { soundFX } from '../audio/SoundFX';
import { getItemMeta } from '../data/items';
import { HudState } from '../types/game';

interface Props {
  hud: HudState;
  itemIcons: Record<string, string>;
  onSelectHotbar: (idx: number) => void;
  onCycleCamera: () => void;
  onOpenCustomizer: () => void;
  onOpenInventory: () => void;
  onOpenHelp: () => void;
  onOpenNearbyNpc: () => void;
  onToggleGameMode: () => void;
  onToggleDayNight: () => void;
  onSpawnDokkaebi: () => void;
  onTeleportVillage: () => void;
  onMobileMove: (mx: number, mz: number, jump: boolean) => void;
  onPrimaryTap: () => void;
  onSecondaryTap: () => void;
  onRotateCamera: (dyaw: number, dpitch: number) => void;
}

export const GameHud: React.FC<Props> = ({
  hud,
  itemIcons,
  onSelectHotbar,
  onCycleCamera,
  onOpenCustomizer,
  onOpenInventory,
  onOpenHelp,
  onOpenNearbyNpc,
  onToggleGameMode,
  onToggleDayNight,
  onSpawnDokkaebi,
  onTeleportVillage,
  onMobileMove,
  onPrimaryTap,
  onSecondaryTap,
  onRotateCamera,
}) => {
  const [muted, setMuted] = useState(soundFX.muted);
  const [showTouchPad, setShowTouchPad] = useState(
    typeof window !== 'undefined' &&
      ('ontouchstart' in window ||
        window.location.hostname === 'kcraft.local' ||
        window.innerWidth < 900)
  );

  const activeSlot = hud.hotbar[hud.hotbarIndex];
  const activeMeta = activeSlot ? getItemMeta(activeSlot.id) : null;

  const cameraLabel =
    hud.cameraMode === 'first_person'
      ? 'اول‌شخص'
      : hud.cameraMode === 'third_back'
      ? 'سوم‌شخص پشت'
      : 'سلفی چهره';

  const hearts = Math.ceil(hud.health / 2);
  const maxHearts = Math.ceil(hud.maxHealth / 2);
  const onigiri = Math.ceil(hud.hunger / 2);
  const maxOnigiri = Math.ceil(hud.maxHunger / 2);

  return (
    <div className="hud-layer">
      {/* Top-Right Player Korean Portrait & Status Card */}
      <div className="hud-player-card">
        <button
          className="hud-portrait-btn"
          title="کلیک برای ویرایش چهره کره‌ای (C)"
          onClick={onOpenCustomizer}
        >
          <img src={hud.playerPortraitUrl} alt={hud.playerNameFa} />
          <span className="edit-face-mini">چهره</span>
        </button>

        <div className="hud-player-stats">
          <div className="hud-name-line">
            <strong>{hud.playerNameFa}</strong>
            <span className="ko-badge">{hud.playerNameKo}</span>
            <span className={`mode-pill ${hud.gameMode}`}>
              {hud.gameMode === 'creative' ? 'خلاقیت ♾️' : 'بقا ⛏️'}
            </span>
          </div>

          <div className="bars-row">
            <div className="stat-icons" title="سلامتی">
              {Array.from({ length: maxHearts }).map((_, i) => (
                <span key={i} className={i < hearts ? 'full' : 'empty'}>
                  ❤️
                </span>
              ))}
            </div>
            <div className="stat-icons" title="انرژی (با کیمباب پر می‌شود)">
              {Array.from({ length: maxOnigiri }).map((_, i) => (
                <span key={i} className={i < onigiri ? 'full' : 'empty'}>
                  🍙
                </span>
              ))}
            </div>
          </div>

          <div className="hud-world-meta">
            <span>{hud.timeLabelFa}</span>
            <span>•</span>
            <span>
              مختصات: {hud.coords.x}, {hud.coords.y}, {hud.coords.z}
            </span>
            <span>•</span>
            <span>اهالی کره‌ای: {hud.totalNpcsInWorld}</span>
            {hud.companionsCount > 0 && (
              <>
                <span>•</span>
                <span className="comp-highlight">یار همراه: {hud.companionsCount}</span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Top-Left Action Toolbar */}
      <div className="hud-action-toolbar">
        <button className="hud-tool-btn highlight-cam" onClick={onCycleCamera}>
          🎥 نما: {cameraLabel} <kbd>V</kbd>
        </button>
        <button className="hud-tool-btn" onClick={onOpenCustomizer}>
          ✨ چهره کره‌ای <kbd>C</kbd>
        </button>
        <button className="hud-tool-btn" onClick={onOpenInventory}>
          🎒 ساخت‌وساز و بلوک‌ها <kbd>E</kbd>
        </button>
        <button className="hud-tool-btn" onClick={onToggleGameMode}>
          {hud.gameMode === 'survival' ? '♾️ حالت خلاقیت' : '⛏️ حالت بقا'} <kbd>G</kbd>
        </button>
        <button className="hud-tool-btn" onClick={onToggleDayNight}>
          {hud.isNight ? '☀️ روز کردن' : '🏮 شب فانوس‌ها'} <kbd>N</kbd>
        </button>
        <button className="hud-tool-btn danger-soft" onClick={onSpawnDokkaebi}>
          ⚔️ احضار دوکه‌بی
        </button>
        <button className="hud-tool-btn" onClick={onTeleportVillage}>
          🏯 میدان هانوک
        </button>
        <button
          className="hud-tool-btn"
          onClick={() => {
            soundFX.muted = !muted;
            setMuted(!muted);
          }}
        >
          {muted ? '🔇 بی‌صدا' : '🔊 صدا'}
        </button>
        <button
          className="hud-tool-btn"
          onClick={() => setShowTouchPad((s) => !s)}
          title="نمایش دکمه‌های لمسی روی صفحه"
        >
          🕹️ کنترل لمسی
        </button>
        <button className="hud-tool-btn" onClick={onOpenHelp}>
          ❓ راهنما <kbd>H</kbd>
        </button>
      </div>

      {/* Center Crosshair & Block Info */}
      {hud.activeModal === 'none' && (
        <div className="crosshair-wrap">
          <div className="mc-crosshair" />
          {hud.breakingProgress > 0.02 && (
            <div className="mining-progress-bar">
              <div style={{ width: `${Math.round(hud.breakingProgress * 100)}%` }} />
            </div>
          )}
          {hud.targetBlockNameFa && (
            <div className="target-block-pill">{hud.targetBlockNameFa}</div>
          )}
        </div>
      )}

      {/* Nearby Friendly Korean Character Prompt */}
      {hud.nearbyNpc && hud.activeModal === 'none' && (
        <button className="nearby-npc-prompt" onClick={onOpenNearbyNpc}>
          <span className="key-cap">F</span>
          <span>
            گفتگو و تبادل با <strong>{hud.nearbyNpc.preset.nameFa}</strong> (
            {hud.nearbyNpc.preset.nameKo}) — {hud.nearbyNpc.preset.roleFa}
          </span>
        </button>
      )}

      {/* Toast Notification */}
      {hud.toastMessage && <div className="hud-toast">{hud.toastMessage}</div>}

      {/* Optional On-Screen Touch / Mouse Controls */}
      {showTouchPad && hud.activeModal === 'none' && (
        <div className="touch-controls-layer">
          <div className="dpad-cluster">
            <button
              className="dpad-btn up"
              onMouseDown={() => onMobileMove(0, 1, false)}
              onMouseUp={() => onMobileMove(0, 0, false)}
              onTouchStart={(e) => {
                e.preventDefault();
                onMobileMove(0, 1, false);
              }}
              onTouchEnd={(e) => {
                e.preventDefault();
                onMobileMove(0, 0, false);
              }}
            >
              ▲
            </button>
            <div className="dpad-mid-row">
              <button
                className="dpad-btn"
                onMouseDown={() => onMobileMove(1, 0, false)}
                onMouseUp={() => onMobileMove(0, 0, false)}
                onTouchStart={(e) => {
                  e.preventDefault();
                  onMobileMove(1, 0, false);
                }}
                onTouchEnd={(e) => {
                  e.preventDefault();
                  onMobileMove(0, 0, false);
                }}
              >
                ▶
              </button>
              <button
                className="dpad-btn jump"
                onMouseDown={() => onMobileMove(0, 0, true)}
                onMouseUp={() => onMobileMove(0, 0, false)}
                onTouchStart={(e) => {
                  e.preventDefault();
                  onMobileMove(0, 0, true);
                }}
                onTouchEnd={(e) => {
                  e.preventDefault();
                  onMobileMove(0, 0, false);
                }}
              >
                پرش
              </button>
              <button
                className="dpad-btn"
                onMouseDown={() => onMobileMove(-1, 0, false)}
                onMouseUp={() => onMobileMove(0, 0, false)}
                onTouchStart={(e) => {
                  e.preventDefault();
                  onMobileMove(-1, 0, false);
                }}
                onTouchEnd={(e) => {
                  e.preventDefault();
                  onMobileMove(0, 0, false);
                }}
              >
                ◀
              </button>
            </div>
            <button
              className="dpad-btn down"
              onMouseDown={() => onMobileMove(0, -1, false)}
              onMouseUp={() => onMobileMove(0, 0, false)}
              onTouchStart={(e) => {
                e.preventDefault();
                onMobileMove(0, -1, false);
              }}
              onTouchEnd={(e) => {
                e.preventDefault();
                onMobileMove(0, 0, false);
              }}
            >
              ▼
            </button>
          </div>

          <div className="touch-actions-cluster">
            <div className="look-mini-row">
              <button className="dpad-btn" onClick={() => onRotateCamera(0.28, 0)}>
                چرخش راست ↻
              </button>
              <button className="dpad-btn" onClick={() => onRotateCamera(-0.28, 0)}>
                ↺ چرخش چپ
              </button>
            </div>
            <div className="action-pair-row">
              <button className="act-btn break" onClick={onPrimaryTap}>
                ⛏️ شکستن / ضربه
              </button>
              <button className="act-btn place" onClick={onSecondaryTap}>
                🧱 گذاشتن / خوردن
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bottom Classic 9-Slot Minecraft Hotbar */}
      <div className="hotbar-dock">
        {activeMeta && (
          <div className="active-item-banner">
            {activeMeta.nameFa} <span className="ko-sub">({activeMeta.nameKo})</span>
          </div>
        )}
        <div className="hotbar-slots">
          {hud.hotbar.map((slot, idx) => {
            const isSelected = hud.hotbarIndex === idx;
            const meta = slot ? getItemMeta(slot.id) : null;
            return (
              <button
                key={idx}
                className={`hotbar-slot ${isSelected ? 'active' : ''}`}
                onClick={() => onSelectHotbar(idx)}
                title={meta ? `${meta.nameFa} (${meta.nameKo})` : `اسلات ${idx + 1}`}
              >
                <span className="slot-key">{idx + 1}</span>
                {slot && (
                  <>
                    <img src={itemIcons[String(slot.id)]} alt={meta?.nameFa} />
                    {slot.count > 1 && <span className="slot-count">{slot.count}</span>}
                  </>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};
