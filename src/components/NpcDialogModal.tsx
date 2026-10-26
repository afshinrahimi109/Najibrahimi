import React, { useState } from 'react';
import { renderCharacterPortraitDataUrl } from '../character/KoreanSkinGenerator';
import { getItemMeta } from '../data/items';
import {
  GameMode,
  InventoryItemId,
  NpcStatusSnapshot,
  TradeOffer,
} from '../types/game';

interface Props {
  npc: NpcStatusSnapshot;
  itemIcons: Record<string, string>;
  gameMode: GameMode;
  countItem: (id: InventoryItemId) => number;
  onTrade: (offer: TradeOffer) => void;
  onToggleFollow: (entityId: string) => void;
  onClose: () => void;
}

export const NpcDialogModal: React.FC<Props> = ({
  npc,
  itemIcons,
  gameMode,
  countItem,
  onTrade,
  onToggleFollow,
  onClose,
}) => {
  const { preset, isFollowing, entityId } = npc;
  const [lineIdx, setLineIdx] = useState(0);

  const portraitUrl = React.useMemo(
    () => renderCharacterPortraitDataUrl(preset.face),
    [preset.face]
  );

  const currentLine =
    preset.dialogLines.length > 0
      ? preset.dialogLines[lineIdx % preset.dialogLines.length]
      : preset.greetingFa;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card npc-dialog-modal" onClick={(e) => e.stopPropagation()}>
        <div className="npc-dialog-top">
          <div className="npc-portrait-wrap">
            <img src={portraitUrl} alt={preset.nameFa} />
            <span className="npc-ko-pill">{preset.nameKo}</span>
          </div>

          <div className="npc-speech-box">
            <div className="npc-title-row">
              <div>
                <h2>{preset.nameFa}</h2>
                <span className="npc-role-tag">{preset.roleFa}</span>
              </div>
              <button className="close-btn" onClick={onClose}>
                ✕ بستن
              </button>
            </div>

            <div className="npc-greeting-ko">{preset.greetingKo}</div>
            <p className="npc-greeting-fa">{preset.greetingFa}</p>
            <div className="npc-tip-bubble">
              «{currentLine}»
              {preset.dialogLines.length > 1 && (
                <button
                  className="next-line-btn"
                  onClick={() => setLineIdx((i) => i + 1)}
                >
                  جمله بعدی ◂
                </button>
              )}
            </div>

            <div className="npc-companion-bar">
              <button
                className={`follow-btn ${isFollowing ? 'following' : ''}`}
                onClick={() => onToggleFollow(entityId)}
              >
                {isFollowing
                  ? '✅ در حال همراهی با شماست (کلیک برای توقف)'
                  : '🤝 همراه من بیا! (تبدیل به یار کمکی)'}
              </button>
            </div>
          </div>
        </div>

        {preset.trades.length > 0 && (
          <div className="npc-trades-section">
            <div className="field-title">پیشنهادهای مبادله و هدیه دهکده کره‌ای:</div>
            <div className="trades-grid">
              {preset.trades.map((t) => {
                const have = countItem(t.giveId);
                const canAfford = gameMode === 'creative' || have >= t.giveCount;
                const giveMeta = getItemMeta(t.giveId);
                const recMeta = getItemMeta(t.receiveId);
                return (
                  <button
                    key={t.id}
                    className={`trade-card ${canAfford ? 'affordable' : 'short'}`}
                    onClick={() => onTrade(t)}
                  >
                    <div className="trade-icons-pair">
                      <div className="trade-item-pill">
                        <img src={itemIcons[String(t.giveId)]} alt={giveMeta.nameFa} />
                        <span>×{t.giveCount}</span>
                      </div>
                      <span className="trade-arrow">⬅</span>
                      <div className="trade-item-pill highlight">
                        <img src={itemIcons[String(t.receiveId)]} alt={recMeta.nameFa} />
                        <span>×{t.receiveCount}</span>
                      </div>
                    </div>
                    <div className="trade-label">{t.labelFa}</div>
                    <div className="trade-stock">
                      موجودی شما: {have} / {t.giveCount}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
