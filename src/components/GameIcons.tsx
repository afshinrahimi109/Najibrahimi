import React from 'react';

interface IconProps {
  size?: number;
  className?: string;
}

export const IconSwordPickaxe: React.FC<IconProps> = ({ size = 30, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <defs>
      <linearGradient id="pickCyan" x1="6" y1="6" x2="40" y2="30" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#99FFFF" />
        <stop offset="55%" stopColor="#1CE5DF" />
        <stop offset="100%" stopColor="#098A9C" />
      </linearGradient>
      <linearGradient id="woodShaft" x1="10" y1="38" x2="36" y2="12" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#6E4427" />
        <stop offset="100%" stopColor="#B87A4B" />
      </linearGradient>
      <linearGradient id="goldGuard" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#FFF099" />
        <stop offset="100%" stopColor="#DDA026" />
      </linearGradient>
    </defs>
    {/* Wooden handle */}
    <path d="M11 39L35 15" stroke="url(#woodShaft)" strokeWidth="5.2" strokeLinecap="round" />
    {/* Diamond Pickaxe Curved Head */}
    <path
      d="M17 11C25 8 34 12 39 20C40.5 22.5 38 25 35.5 23C31.5 18 26 15.5 19.5 16.5C16.5 17 14.5 12 17 11Z"
      fill="url(#pickCyan)"
      stroke="#E6FFFF"
      strokeWidth="1.4"
    />
    {/* Gold Collar */}
    <circle cx="32" cy="18" r="3.4" fill="url(#goldGuard)" />
    {/* Sparkle */}
    <path d="M12 18L14 14L16 18L20 20L16 22L14 26L12 22L8 20L12 18Z" fill="#FFF6B3" />
  </svg>
);

export const IconVoxelBuild: React.FC<IconProps> = ({ size = 28, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    {/* Top face */}
    <polygon points="24,7 41,16 24,25 7,16" fill="#7BF16B" stroke="#E9FFE4" strokeWidth="1.3" />
    {/* Left face */}
    <polygon points="7,16 24,25 24,42 7,33" fill="#46A844" stroke="#265E28" strokeWidth="1.2" />
    {/* Right face */}
    <polygon points="41,16 24,25 24,42 41,33" fill="#2F7E36" stroke="#1E5223" strokeWidth="1.2" />
    {/* Plus badge */}
    <circle cx="37" cy="12" r="7" fill="#FFD15C" stroke="#FFF8DC" strokeWidth="1.5" />
    <path d="M37 8.5V15.5M33.5 12H40.5" stroke="#3A2505" strokeWidth="2.4" strokeLinecap="round" />
  </svg>
);

export const IconWingJump: React.FC<IconProps> = ({ size = 28, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <defs>
      <linearGradient id="jumpSky" x1="24" y1="6" x2="24" y2="42" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#FFFFFF" />
        <stop offset="55%" stopColor="#7DE2FF" />
        <stop offset="100%" stopColor="#2692E8" />
      </linearGradient>
    </defs>
    <path
      d="M24 8L37 22H29V36C29 37.7 27.7 39 26 39H22C20.3 39 19 37.7 19 36V22H11L24 8Z"
      fill="url(#jumpSky)"
      stroke="#E6FAFF"
      strokeWidth="1.5"
      strokeLinejoin="round"
    />
    <path
      d="M9 31C6 27 7 20 12 18M39 31C42 27 41 20 36 18"
      stroke="#B8F2FF"
      strokeWidth="2.6"
      strokeLinecap="round"
    />
  </svg>
);

export const IconTurboBoots: React.FC<IconProps> = ({ size = 22, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <path
      d="M27 6L12 26H24L20 42L37 21H25L27 6Z"
      fill="#FFD24C"
      stroke="#FFF7D6"
      strokeWidth="1.8"
      strokeLinejoin="round"
    />
  </svg>
);

export const IconCraneFlight: React.FC<IconProps> = ({ size = 22, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <path
      d="M24 28C18 17 9 13 4 15C7 22 12 27 20 30L24 36L28 30C36 27 41 22 44 15C39 13 30 17 24 28Z"
      fill="#9EF8F2"
      stroke="#FFFFFF"
      strokeWidth="1.8"
      strokeLinejoin="round"
    />
    <circle cx="24" cy="14" r="3.5" fill="#FFE27A" />
  </svg>
);

export const IconChevron3D: React.FC<
  IconProps & { dir: 'up' | 'down' | 'left' | 'right'; active?: boolean }
> = ({ size = 24, dir, active, className }) => {
  const rot =
    dir === 'up' ? 0 : dir === 'right' ? 90 : dir === 'down' ? 180 : 270;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      className={className}
      style={{ transform: `rotate(${rot}deg)` }}
    >
      <defs>
        <linearGradient id={`chev_${dir}`} x1="20" y1="6" x2="20" y2="34" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor={active ? '#FFF5B8' : '#B8F7FF'} />
          <stop offset="100%" stopColor={active ? '#F5A623' : '#26B6D4'} />
        </linearGradient>
      </defs>
      <path
        d="M20 7L34 23C35.2 24.4 34.2 26.5 32.4 26.5H25V32C25 33.1 24.1 34 23 34H17C15.9 34 15 33.1 15 32V26.5H7.6C5.8 26.5 4.8 24.4 6 23L20 7Z"
        fill={`url(#chev_${dir})`}
        stroke="#FFFFFF"
        strokeWidth="1.5"
      />
    </svg>
  );
};

export const IconBackpack: React.FC<IconProps> = ({ size = 24, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <path d="M18 12C18 8.5 20.7 6 24 6C27.3 6 30 8.5 30 12" stroke="#FFD166" strokeWidth="3.5" strokeLinecap="round" />
    <rect x="10" y="12" width="28" height="30" rx="8" fill="#2A9D8F" stroke="#A8FFF0" strokeWidth="1.8" />
    <path d="M10 22H38" stroke="#185E56" strokeWidth="2.5" />
    <rect x="20" y="19" width="8" height="7" rx="2" fill="#FFD166" />
    <rect x="15" y="29" width="18" height="9" rx="3" fill="#1F776D" stroke="#7AE8DC" strokeWidth="1.2" />
  </svg>
);

export const IconKoreanFace: React.FC<IconProps> = ({ size = 24, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    {/* Cute Voxel Korean Head with Gat Crown */}
    <rect x="12" y="15" width="24" height="23" rx="6" fill="#FCE0CE" stroke="#FFF5EE" strokeWidth="1.6" />
    {/* Stylish Two-Block Hair */}
    <path d="M11 21C11 14 16 11 24 11C32 11 37 14 37 21C33 18 28 18 24 20C20 18 15 18 11 21Z" fill="#232530" />
    {/* Traditional Ribbon / Crown Accent */}
    <rect x="18" y="6" width="12" height="5" rx="2" fill="#FF6B9D" />
    {/* Smiling Eyes */}
    <path d="M17 26C18.2 24.5 20.3 24.5 21.5 26" stroke="#1E2029" strokeWidth="2.4" strokeLinecap="round" />
    <path d="M26.5 26C27.7 24.5 29.8 24.5 31 26" stroke="#1E2029" strokeWidth="2.4" strokeLinecap="round" />
    {/* Rosy Blush */}
    <circle cx="16.5" cy="30" r="2.2" fill="#FF8FAB" opacity="0.75" />
    <circle cx="31.5" cy="30" r="2.2" fill="#FF8FAB" opacity="0.75" />
    {/* Warm Smile */}
    <path d="M21 32C22.2 33.6 25.8 33.6 27 32" stroke="#D94E67" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);

export const IconQuestScroll: React.FC<IconProps> = ({ size = 24, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <rect x="11" y="8" width="26" height="32" rx="4" fill="#FFF3D1" stroke="#F4B942" strokeWidth="2" />
    <rect x="8" y="6" width="32" height="6" rx="3" fill="#E09F24" />
    <rect x="8" y="36" width="32" height="6" rx="3" fill="#E09F24" />
    <path d="M24 15L26.2 19.6L31.2 20.3L27.6 23.8L28.5 28.8L24 26.4L19.5 28.8L20.4 23.8L16.8 20.3L21.8 19.6L24 15Z" fill="#FF6B6B" />
  </svg>
);

export const IconWorldGlobe: React.FC<IconProps> = ({ size = 24, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <circle cx="24" cy="24" r="17" fill="#2389DA" stroke="#A6E8FF" strokeWidth="2" />
    <path
      d="M14 17C18 15 22 17 24 21C26 25 32 23 36 26C34 33 27 37 20 35C15 33 12 24 14 17Z"
      fill="#59C965"
    />
    <path d="M26 10C30 11 34 14 35 18C31 19 27 16 26 10Z" fill="#FF9EBB" />
  </svg>
);

export const IconVillagers: React.FC<IconProps> = ({ size = 24, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <circle cx="17" cy="17" r="7" fill="#FAD6C0" stroke="#FFF" strokeWidth="1.5" />
    <path d="M7 38C7 31.5 11.5 27 17 27C22.5 27 27 31.5 27 38" fill="#FF7597" />
    <circle cx="32" cy="18" r="6.5" fill="#F5C8AE" stroke="#FFF" strokeWidth="1.5" />
    <path d="M23 38C23 32 27 28 32 28C37 28 41 32 41 38" fill="#43B0F1" />
  </svg>
);

export const IconSettingsGear: React.FC<IconProps> = ({ size = 24, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <circle cx="24" cy="24" r="14" fill="#4A5568" stroke="#CBD5E1" strokeWidth="3" strokeDasharray="6 4" />
    <circle cx="24" cy="24" r="7" fill="#FFD166" stroke="#FFF" strokeWidth="1.8" />
  </svg>
);

export const IconMenuShield: React.FC<IconProps> = ({ size = 22, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <rect x="8" y="10" width="32" height="5" rx="2.5" fill="#FFE082" />
    <rect x="8" y="21.5" width="32" height="5" rx="2.5" fill="#80DEEA" />
    <rect x="8" y="33" width="32" height="5" rx="2.5" fill="#FF8A80" />
  </svg>
);

export const IconCameraView: React.FC<IconProps> = ({ size = 22, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <rect x="7" y="14" width="34" height="24" rx="6" fill="#3B82F6" stroke="#DBEAFE" strokeWidth="2" />
    <path d="M17 14L20 9H28L31 14" fill="#60A5FA" />
    <circle cx="24" cy="26" r="7" fill="#0F172A" stroke="#93C5FD" strokeWidth="2.2" />
    <circle cx="26" cy="24" r="2" fill="#FFFFFF" />
  </svg>
);

export const IconChatBubble: React.FC<IconProps> = ({ size = 24, className }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" fill="none" className={className}>
    <path
      d="M8 15C8 10.6 11.6 7 16 7H32C36.4 7 40 10.6 40 15V26C40 30.4 36.4 34 32 34H21L12 41V34C9.7 33.2 8 30 8 26V15Z"
      fill="#FF6B9D"
      stroke="#FFE3EE"
      strokeWidth="2"
      strokeLinejoin="round"
    />
    <circle cx="18" cy="20.5" r="2.5" fill="#FFFFFF" />
    <circle cx="24" cy="20.5" r="2.5" fill="#FFFFFF" />
    <circle cx="30" cy="20.5" r="2.5" fill="#FFFFFF" />
  </svg>
);

export const IconHeartGlossy: React.FC<IconProps> = ({ size = 18, className }) => (
  <svg width={size} height={size} viewBox="0 0 36 36" fill="none" className={className}>
    <path
      d="M18 31C18 31 4 22.2 4 12.5C4 7.8 7.7 4 12.2 4C15 4 17.1 5.5 18 7.4C18.9 5.5 21 4 23.8 4C28.3 4 32 7.8 32 12.5C32 22.2 18 31 18 31Z"
      fill="#FF3B5C"
      stroke="#FFD1DA"
      strokeWidth="1.6"
    />
    <ellipse cx="11.5" cy="10.5" rx="3" ry="1.8" transform="rotate(-25 11.5 10.5)" fill="#FF9EB0" />
  </svg>
);

export const IconEnergyBolt: React.FC<IconProps> = ({ size = 18, className }) => (
  <svg width={size} height={size} viewBox="0 0 36 36" fill="none" className={className}>
    <path
      d="M20 3L8 19H17L15 33L28 16H19L20 3Z"
      fill="#FFB72B"
      stroke="#FFF2B2"
      strokeWidth="1.5"
      strokeLinejoin="round"
    />
  </svg>
);

export const IconGoldCoin: React.FC<IconProps> = ({ size = 18, className }) => (
  <svg width={size} height={size} viewBox="0 0 36 36" fill="none" className={className}>
    <circle cx="18" cy="18" r="14" fill="#FFD147" stroke="#FFF5C0" strokeWidth="2" />
    <circle cx="18" cy="18" r="9.5" fill="#F5A623" />
    <rect x="15" y="15" width="6" height="6" rx="1" fill="#FFF3B8" />
  </svg>
);
