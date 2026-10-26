import React from 'react';
import { KOREAN_CHARACTER_PRESETS } from '../character/KoreanPresets';
import { renderCharacterPortraitDataUrl } from '../character/KoreanSkinGenerator';
import {
  BeautyMarkId,
  BrowStyleId,
  CharacterPreset,
  EyeStyleId,
  GlassesStyleId,
  HairStyleId,
  KoreanFaceConfig,
  LipStyleId,
  OutfitStyleId,
  SkinToneId,
} from '../types/game';

interface Props {
  face: KoreanFaceConfig;
  playerNameFa: string;
  playerNameKo: string;
  onUpdateFace: (partial: Partial<KoreanFaceConfig>) => void;
  onSelectPreset: (preset: CharacterPreset) => void;
  onClose: () => void;
}

const SKIN_OPTIONS: Array<{ id: SkinToneId; label: string; swatch: string }> = [
  { id: 'porcelain', label: 'روشن سئولی', swatch: '#FCE3D2' },
  { id: 'warm_ivory', label: 'عاجی ملایم', swatch: '#F8D7BE' },
  { id: 'natural_peach', label: 'هلویی طبیعی', swatch: '#F1C8AA' },
  { id: 'honey_warm', label: 'گندمی گرم', swatch: '#E6B794' },
];

const EYE_OPTIONS: Array<{ id: EyeStyleId; label: string }> = [
  { id: 'monolid', label: 'تک‌پلک کره‌ای (무쌍)' },
  { id: 'soft_double', label: 'دوپلک ظریف (속쌍)' },
  { id: 'eye_smile', label: 'چشم خندان (눈웃음)' },
  { id: 'sharp_warrior', label: 'نگاه جنگجوی چوسان' },
  { id: 'gentle_elder', label: 'مهربان سنتی' },
];

const BROW_OPTIONS: Array<{ id: BrowStyleId; label: string }> = [
  { id: 'straight_soft', label: 'ابروی صاف کره‌ای (일자)' },
  { id: 'straight_bold', label: 'ابروی پرپشت مردانه' },
  { id: 'arched_idol', label: 'ابروی ملایم آیدل' },
  { id: 'elder_silver', label: 'ابروی نقره‌ای' },
];

const HAIR_OPTIONS: Array<{ id: HairStyleId; label: string }> = [
  { id: 'comma_twoblock', label: 'کاما دوطبقه کی‌پاپ' },
  { id: 'seethrough_long', label: 'چتری سی‌ترو و روبان دنگی' },
  { id: 'joseon_gat', label: 'کلاه سنتی گات چوسان (갓)' },
  { id: 'idol_layered', label: 'لایه‌ای سئول با گیره' },
  { id: 'binyeo_bun', label: 'شینیون با سنجاق یشم (비녀)' },
  { id: 'student_cut', label: 'مدل دانشجویی سئول' },
  { id: 'satgat_farmer', label: 'کلاه حصیری سات‌گات (삿갓)' },
  { id: 'halmeoni_perm', label: 'فر کلاسیک مادربزرگ' },
];

const HAIR_COLORS = [
  { hex: '#16161E', label: 'مشکی پرکلاغی' },
  { hex: '#241B17', label: 'قهوه‌ای اسپرسو' },
  { hex: '#3D271F', label: 'بلوطی سئول' },
  { hex: '#5E3D31', label: 'فندقی روشن' },
  { hex: '#7D808A', label: 'نقره‌ای سنتی' },
];

const LIP_OPTIONS: Array<{ id: LipStyleId; label: string }> = [
  { id: 'natural_warm', label: 'طبیعی گرم' },
  { id: 'kbeauty_rose', label: 'تینت رز کره‌ای' },
  { id: 'coral_gradient', label: 'گرادیان مرجانی' },
  { id: 'berry_tint', label: 'تینت آلبالویی' },
];

const GLASSES_OPTIONS: Array<{ id: GlassesStyleId; label: string }> = [
  { id: 'none', label: 'بدون عینک' },
  { id: 'seoul_round', label: 'عینک گرد سئولی (동글이)' },
  { id: 'tinted_idol', label: 'عینک طلایی آیدل' },
];

const BEAUTY_MARK_OPTIONS: Array<{ id: BeautyMarkId; label: string }> = [
  { id: 'none', label: 'بدون خال' },
  { id: 'under_eye', label: 'خال زیر چشم (눈물점)' },
  { id: 'cheek', label: 'خال گونه' },
];

const OUTFIT_OPTIONS: Array<{ id: OutfitStyleId; label: string }> = [
  { id: 'seoul_street', label: 'استایل خیابانی سئول' },
  { id: 'hanbok_pink', label: 'هانبوک صورتی بهاری' },
  { id: 'hanbok_royal', label: 'هانبوک سلطنتی' },
  { id: 'joseon_guard', label: 'زره نگهبان چوسان' },
  { id: 'student_hoodie', label: 'هودی دانشگاه سئول' },
  { id: 'hanbok_apron', label: 'هانبوک هنرمند' },
  { id: 'halmeoni_vest', label: 'جلیقه گل‌دار بازار' },
  { id: 'carpenter_hemp', label: 'لباس کتانی معمار' },
];

export const FaceCustomizerModal: React.FC<Props> = ({
  face,
  playerNameFa,
  playerNameKo,
  onUpdateFace,
  onSelectPreset,
  onClose,
}) => {
  const portraitUrl = React.useMemo(() => renderCharacterPortraitDataUrl(face), [face]);
  const playablePresets = KOREAN_CHARACTER_PRESETS.filter((p) => p.isPlayable);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card customizer-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>استودیو طراحی چهره و لباس کره‌ای</h2>
            <p className="modal-subtitle">
              تمام شخصیت‌های کی‌کرفت دارای اجزای چهره، مدل مو و پوشش اصیل کره‌ای هستند
            </p>
          </div>
          <button className="close-btn" onClick={onClose}>
            ✕ بستن
          </button>
        </div>

        <div className="customizer-layout">
          {/* Preview Column */}
          <div className="customizer-preview-col">
            <div className="portrait-frame-lg">
              <img src={portraitUrl} alt={playerNameFa} />
            </div>
            <div className="preview-name-box">
              <strong>{playerNameFa}</strong>
              <span>{playerNameKo}</span>
            </div>

            <div className="preset-mini-section">
              <span className="field-title">شخصیت‌های آماده کره‌ای:</span>
              <div className="preset-mini-list">
                {playablePresets.map((p) => (
                  <button
                    key={p.id}
                    className={`preset-chip ${playerNameFa === p.nameFa ? 'active' : ''}`}
                    onClick={() => onSelectPreset(p)}
                  >
                    {p.nameFa} ({p.nameKo})
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Controls Column */}
          <div className="customizer-controls-col">
            <div className="control-group">
              <label className="field-title">تناژ پوست کره‌ای:</label>
              <div className="swatch-row">
                {SKIN_OPTIONS.map((s) => (
                  <button
                    key={s.id}
                    className={`option-pill ${face.skinTone === s.id ? 'selected' : ''}`}
                    onClick={() => onUpdateFace({ skinTone: s.id })}
                  >
                    <span className="color-dot" style={{ background: s.swatch }} />
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="control-group">
              <label className="field-title">فرم چشم کره‌ای (눈매):</label>
              <div className="pill-grid">
                {EYE_OPTIONS.map((o) => (
                  <button
                    key={o.id}
                    className={`option-pill ${face.eyeStyle === o.id ? 'selected' : ''}`}
                    onClick={() => onUpdateFace({ eyeStyle: o.id })}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="control-group">
              <label className="field-title">مدل مو و کلاه سنتی کره‌ای:</label>
              <div className="pill-grid">
                {HAIR_OPTIONS.map((o) => (
                  <button
                    key={o.id}
                    className={`option-pill ${face.hairStyle === o.id ? 'selected' : ''}`}
                    onClick={() => onUpdateFace({ hairStyle: o.id })}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="control-group">
              <label className="field-title">رنگ مو و فرم ابرو:</label>
              <div className="swatch-row" style={{ marginBottom: 8 }}>
                {HAIR_COLORS.map((c) => (
                  <button
                    key={c.hex}
                    className={`option-pill ${
                      face.hairColor.toLowerCase() === c.hex.toLowerCase() ? 'selected' : ''
                    }`}
                    onClick={() => onUpdateFace({ hairColor: c.hex })}
                  >
                    <span className="color-dot" style={{ background: c.hex }} />
                    {c.label}
                  </button>
                ))}
              </div>
              <div className="pill-grid">
                {BROW_OPTIONS.map((o) => (
                  <button
                    key={o.id}
                    className={`option-pill ${face.browStyle === o.id ? 'selected' : ''}`}
                    onClick={() => onUpdateFace({ browStyle: o.id })}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="control-group">
              <label className="field-title">تینت لب، عینک و جزئیات چهره:</label>
              <div className="pill-grid" style={{ marginBottom: 8 }}>
                {LIP_OPTIONS.map((o) => (
                  <button
                    key={o.id}
                    className={`option-pill ${face.lipStyle === o.id ? 'selected' : ''}`}
                    onClick={() => onUpdateFace({ lipStyle: o.id })}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
              <div className="pill-grid">
                {GLASSES_OPTIONS.map((o) => (
                  <button
                    key={o.id}
                    className={`option-pill ${face.glasses === o.id ? 'selected' : ''}`}
                    onClick={() => onUpdateFace({ glasses: o.id })}
                  >
                    {o.label}
                  </button>
                ))}
                {BEAUTY_MARK_OPTIONS.map((o) => (
                  <button
                    key={o.id}
                    className={`option-pill ${face.beautyMark === o.id ? 'selected' : ''}`}
                    onClick={() => onUpdateFace({ beautyMark: o.id })}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="control-group">
              <label className="field-title">پوشش (هانبوک، چوسان و استایل سئول):</label>
              <div className="pill-grid">
                {OUTFIT_OPTIONS.map((o) => (
                  <button
                    key={o.id}
                    className={`option-pill ${face.outfitStyle === o.id ? 'selected' : ''}`}
                    onClick={() => onUpdateFace({ outfitStyle: o.id })}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="modal-footer">
          <button className="primary-cta-btn" onClick={onClose}>
            تأیید چهره و بازگشت به بازی ✨
          </button>
        </div>
      </div>
    </div>
  );
};
