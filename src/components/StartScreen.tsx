import React from 'react';
import { KOREAN_CHARACTER_PRESETS } from '../character/KoreanPresets';
import { renderCharacterPortraitDataUrl } from '../character/KoreanSkinGenerator';
import { CharacterPreset, GameMode, KoreanFaceConfig } from '../types/game';

interface Props {
  selectedNameFa: string;
  selectedNameKo: string;
  playerFace: KoreanFaceConfig;
  gameMode: GameMode;
  onSelectPreset: (preset: CharacterPreset) => void;
  onToggleGameMode: () => void;
  onOpenCustomizer: () => void;
  onStartGame: () => void;
}

export const StartScreen: React.FC<Props> = ({
  selectedNameFa,
  selectedNameKo,
  playerFace,
  gameMode,
  onSelectPreset,
  onToggleGameMode,
  onOpenCustomizer,
  onStartGame,
}) => {
  const playable = React.useMemo(
    () => KOREAN_CHARACTER_PRESETS.filter((p) => p.isPlayable),
    []
  );

  const presetPortraits = React.useMemo(() => {
    const map: Record<string, string> = {};
    for (const p of playable) {
      map[p.id] = renderCharacterPortraitDataUrl(p.face);
    }
    return map;
  }, [playable]);

  const currentPortrait = React.useMemo(
    () => renderCharacterPortraitDataUrl(playerFace),
    [playerFace]
  );

  const selectedBio =
    playable.find((p) => p.nameFa === selectedNameFa)?.bioFa ??
    'شخصیت اختصاصی شما با چهره و پوشش کره‌ای آماده ماجراجویی در دنیای بلوکی است!';

  return (
    <div className="start-screen-overlay">
      <div className="start-card">
        <div className="start-brand-header">
          <div className="brand-badge">K-CRAFT • 마인크래프트 한국 마을</div>
          <h1>کی‌کرفت | ماین‌کرفت کره‌ای</h1>
          <p>
            شبیه‌ساز سه‌بعدی ماین‌کرفت با معماری عمارت‌های هانوک، شکوفه‌های گیلاس و شخصیت‌هایی که
            همگی چهره و پوشش اصیل کره‌ای دارند
          </p>
        </div>

        <div className="start-body-grid">
          {/* Active Hero Character Card */}
          <div className="hero-selected-card">
            <img src={currentPortrait} alt={selectedNameFa} className="hero-portrait-img" />
            <div className="hero-meta">
              <h3>
                {selectedNameFa} <span className="ko-tag">{selectedNameKo}</span>
              </h3>
              <p>{selectedBio}</p>
              <button className="secondary-btn" onClick={onOpenCustomizer}>
                🎨 ویرایش اجزای چهره و لباس کره‌ای
              </button>
            </div>
          </div>

          {/* Character Roster Grid */}
          <div className="roster-section">
            <div className="section-label">شخصیت کره‌ای خودت رو انتخاب کن:</div>
            <div className="roster-grid">
              {playable.map((preset) => {
                const isSelected = preset.nameFa === selectedNameFa;
                return (
                  <button
                    key={preset.id}
                    className={`roster-card ${isSelected ? 'active' : ''}`}
                    onClick={() => onSelectPreset(preset)}
                  >
                    <img src={presetPortraits[preset.id]} alt={preset.nameFa} />
                    <span className="roster-name-fa">{preset.nameFa}</span>
                    <span className="roster-name-ko">{preset.nameKo}</span>
                    <span className="roster-role">{preset.roleFa}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="start-controls-strip">
          <span>حرکت: WASD + Space</span>
          <span>کندن بلوک / حمله: کلیک چپ</span>
          <span>گذاشتن بلوک / خوردن کیمباب: کلیک راست (یا R)</span>
          <span>چهره خودت (سوم‌شخص): V</span>
          <span>گفتگو با اهالی کره‌ای: F</span>
        </div>

        <div className="start-actions-row">
          <button className="mode-toggle-btn" onClick={onToggleGameMode}>
            حالت بازی:{' '}
            <strong>
              {gameMode === 'survival' ? '⛏️ بقا و معدن‌کاری (Survival)' : '♾️ خلاقیت بی‌نهایت (Creative)'}
            </strong>
          </button>

          <button className="start-play-btn" onClick={onStartGame}>
            ورود به دنیای ماین‌کرفت کره‌ای ◀
          </button>
        </div>
      </div>
    </div>
  );
};
