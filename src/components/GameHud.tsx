import React, { useState } from 'react';
import { soundFX } from '../audio/SoundFX';
import { getItemMeta } from '../data/items';
import { HudState } from '../types/game';
import { MobileControls } from './MobileControls';
import { LiveDialogueStream } from './LiveDialogueStream';

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
  onSetFlyDown: (down: boolean) => void;
  onSetJumping: (jumping: boolean) => void;
  onToggleFlight: () => void;
  onToggleSprint: () => void;
  onQuickGreet: (npcId: string) => void;
  onSetControlStyle: (style: HudState['controlStyle']) => void;
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
  onSetFlyDown,
  onSetJumping,
  onToggleFlight,
  onToggleSprint,
  onQuickGreet,
  onSetControlStyle,
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

      {/* Smart touch control zones: analog stick or sculpted 3D D-pad + context actions */}
      {showTouchPad && hud.activeModal === 'none' && (
        <MobileControls
          controlStyle={hud.controlStyle}
          isFlying={hud.isFlying}
          sprinting={hud.sprinting}
          secondaryActionLabel={activeMeta?.category === 'food' ? 'خوردن' : activeMeta?.isBlock ? 'گذاشتن' : 'استفاده'}
          onMoveVector={(mx, mz) => onMobileMove(mx, mz, false)}
          onSetJump={onSetJumping}
          onSetFlyDown={onSetFlyDown}
          onPrimaryTap={onPrimaryTap}
          onSecondaryTap={onSecondaryTap}
          onToggleSprint={onToggleSprint}
          onToggleFlight={onToggleFlight}
        />
      )}

      {/* Villager dialogue bubbles intelligently enter and leave without covering controls */}
      {hud.activeModal === 'none' && (
        <LiveDialogueStream
          messages={hud.liveChatFeed}
          nearbyNpc={hud.nearbyNpc}
          onQuickGreetNearby={(npc) => onQuickGreet(npc.entityId)}
          onOpenFullDialog={onOpenNearbyNpc}
        />
      )}

      {showTouchPad && hud.activeModal === 'none' && (
        <button
          className="control-mode-switch"
          type="button"
          title="تغییر روش کنترل حرکت"
          onClick={() => onSetControlStyle(hud.controlStyle === 'joystick' ? 'dpad' : 'joystick')}
        >
          {hud.controlStyle === 'joystick' ? '◈ جوی‌استیک' : '✣ جهت‌نما'}
        </button>
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
