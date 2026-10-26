import React from 'react';

interface Props {
  onClose: () => void;
}

export const HelpModal: React.FC<Props> = ({ onClose }) => {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card help-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>راهنمای کامل کی‌کرفت (ماین‌کرفت کره‌ای)</h2>
            <p className="modal-subtitle">کنترل‌ها، امکانات ساخت‌وساز و تعامل با اهالی کره‌ای دهکده</p>
          </div>
          <button className="close-btn" onClick={onClose}>
            ✕ بستن
          </button>
        </div>

        <div className="help-grid">
          <div className="help-box">
            <h3>🎮 حرکت و دوربین</h3>
            <ul>
              <li>
                <strong>W / A / S / D:</strong> راه رفتن در چهار جهت (با <strong>Shift</strong> دویدن)
              </li>
              <li>
                <strong>Space:</strong> پرش از موانع و شنا در برکه آب
              </li>
              <li>
                <strong>ماوس (یا کشیدن ماوس / کلیدهای جهت‌نما):</strong> چرخش دوربین به اطراف
              </li>
              <li>
                <strong>کلید V:</strong> تغییر دوربین بین اول‌شخص، سوم‌شخص از پشت و{' '}
                <strong>سلفی روبه‌رو چهره کره‌ای</strong>
              </li>
            </ul>
          </div>

          <div className="help-box">
            <h3>⛏️ معدن‌کاری و ساخت‌وساز</h3>
            <ul>
              <li>
                <strong>نگه داشتن کلیک چپ:</strong> شکستن تدریجی بلوک‌ها و استخراج سنگ، زغال، آهن،
                طلا و الماس
              </li>
              <li>
                <strong>کلیک راست (یا کلید R):</strong> قرار دادن بلوک انتخاب‌شده یا خوردن کیمباب و
                توکبوکی
              </li>
              <li>
                <strong>کلیدهای ۱ تا ۹ (یا اسکرول ماوس):</strong> انتخاب ابزار یا بلوک در نوار پایین
              </li>
              <li>
                <strong>کلید E:</strong> باز کردن میز ساخت‌وساز، کوله‌پشتی و کاتالوگ تمام بلوک‌ها
              </li>
            </ul>
          </div>

          <div className="help-box">
            <h3>🇰🇷 شخصیت‌ها و فرهنگ کره‌ای</h3>
            <ul>
              <li>
                <strong>کلید C:</strong> باز کردن استودیو طراحی چهره کره‌ای (فرم چشم تک‌پلک، دوپلک،
                چشم خندان، کلاه گات چوسان، هانبوک و استایل سئول)
              </li>
              <li>
                <strong>کلید F (یا کلیک راست روی اهالی):</strong> گفتگو، دریافت هدیه، معامله و دعوت
                از شخصیت‌های کره‌ای برای همراهی شما!
              </li>
              <li>
                <strong>کلید G:</strong> تغییر سریع بین حالت <em>بقا</em> و <em>خلاقیت بی‌نهایت</em>
              </li>
              <li>
                <strong>کلید N:</strong> تغییر روز بهاری و شب فانوس‌های ابریشمی (청사초롱)
              </li>
            </ul>
          </div>
        </div>

        <div className="modal-footer">
          <button className="primary-cta-btn" onClick={onClose}>
            متوجه شدم، ادامه بازی!
          </button>
        </div>
      </div>
    </div>
  );
};
