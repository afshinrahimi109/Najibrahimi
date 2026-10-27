import React, { useRef, useState } from 'react';
import { ControlStyle } from '../types/game';
import {
  IconChevron3D,
  IconCraneFlight,
  IconSwordPickaxe,
  IconTurboBoots,
  IconVoxelBuild,
  IconWingJump,
} from './GameIcons';

interface MobileControlsProps {
  controlStyle: ControlStyle;
  isFlying: boolean;
  sprinting: boolean;
  secondaryActionLabel: string;
  onMoveVector: (mx: number, mz: number) => void;
  onSetJump: (jumping: boolean) => void;
  onSetFlyDown: (down: boolean) => void;
  onPrimaryTap: () => void;
  onSecondaryTap: () => void;
  onToggleSprint: () => void;
  onToggleFlight: () => void;
}

export const MobileControls: React.FC<MobileControlsProps> = ({
  controlStyle,
  isFlying,
  sprinting,
  secondaryActionLabel,
  onMoveVector,
  onSetJump,
  onSetFlyDown,
  onPrimaryTap,
  onSecondaryTap,
  onToggleSprint,
  onToggleFlight,
}) => {
  const baseRef = useRef<HTMLDivElement | null>(null);
  const activeTouchId = useRef<number | null>(null);
  const [knob, setKnob] = useState<{ x: number; y: number; active: boolean }>({
    x: 0,
    y: 0,
    active: false,
  });
  const [pressedDir, setPressedDir] = useState<string | null>(null);

  const MAX_RADIUS = 42;
  const pulse = () => {
    if (typeof navigator !== 'undefined' && 'vibrate' in navigator) navigator.vibrate?.(9);
  };

  const updateStickFromPoint = (clientX: number, clientY: number) => {
    const el = baseRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    let dx = clientX - cx;
    let dy = clientY - cy;
    const dist = Math.hypot(dx, dy);
    if (dist > MAX_RADIUS) {
      dx = (dx / dist) * MAX_RADIUS;
      dy = (dy / dist) * MAX_RADIUS;
    }
    setKnob({ x: dx, y: dy, active: true });
    // mx: right is +1, mz: forward (up on screen, negative dy) is +1
    const normX = Math.abs(dx) < 5 ? 0 : dx / MAX_RADIUS;
    const normZ = Math.abs(dy) < 5 ? 0 : -dy / MAX_RADIUS;
    onMoveVector(normX, normZ);
  };

  const resetStick = () => {
    activeTouchId.current = null;
    setKnob({ x: 0, y: 0, active: false });
    onMoveVector(0, 0);
  };

  const handleTouchStart = (e: React.TouchEvent) => {
    e.stopPropagation();
    if (activeTouchId.current === null && e.changedTouches.length > 0) {
      const t = e.changedTouches[0];
      activeTouchId.current = t.identifier;
      updateStickFromPoint(t.clientX, t.clientY);
    }
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    e.stopPropagation();
    for (let i = 0; i < e.changedTouches.length; i++) {
      const t = e.changedTouches[i];
      if (t.identifier === activeTouchId.current) {
        updateStickFromPoint(t.clientX, t.clientY);
        break;
      }
    }
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    e.stopPropagation();
    for (let i = 0; i < e.changedTouches.length; i++) {
      if (e.changedTouches[i].identifier === activeTouchId.current) {
        resetStick();
        break;
      }
    }
  };

  const bindDpadBtn = (dir: 'up' | 'down' | 'left' | 'right', mx: number, mz: number) => ({
    onPointerDown: (e: React.PointerEvent) => {
      e.stopPropagation();
      e.preventDefault();
      setPressedDir(dir);
      onMoveVector(mx, mz);
    },
    onPointerUp: (e: React.PointerEvent) => {
      e.stopPropagation();
      setPressedDir(null);
      onMoveVector(0, 0);
    },
    onPointerLeave: () => {
      if (pressedDir === dir) {
        setPressedDir(null);
        onMoveVector(0, 0);
      }
    },
    onPointerCancel: () => {
      setPressedDir(null);
      onMoveVector(0, 0);
    },
  });

  return (
    <>
      {/* LEFT ZONE: Pro 360° Analog Joystick OR Sculpted 3D Gamepad Cross */}
      <div className="mc-left-pad" dir="ltr">
        {controlStyle === 'joystick' ? (
          <div
            ref={baseRef}
            className={`analog-base ${knob.active ? 'is-active' : ''}`}
            onTouchStart={handleTouchStart}
            onTouchMove={handleTouchMove}
            onTouchEnd={handleTouchEnd}
            onTouchCancel={handleTouchEnd}
            onMouseDown={(e) => {
              e.stopPropagation();
              updateStickFromPoint(e.clientX, e.clientY);
              const move = (ev: MouseEvent) => updateStickFromPoint(ev.clientX, ev.clientY);
              const up = () => {
                resetStick();
                window.removeEventListener('mousemove', move);
                window.removeEventListener('mouseup', up);
              };
              window.addEventListener('mousemove', move);
              window.addEventListener('mouseup', up);
            }}
          >
            <div className="analog-ring-decor" />
            <span className="analog-tick tick-n" />
            <span className="analog-tick tick-e" />
            <span className="analog-tick tick-s" />
            <span className="analog-tick tick-w" />
            <div
              className="analog-Stick-orb"
              style={{
                transform: `translate(${knob.x}px, ${knob.y}px) scale(${knob.active ? 1.08 : 1})`,
              }}
            >
              <div className="analog-orb-core" />
            </div>
          </div>
        ) : (
          <div className="sculpted-dpad">
            <button
              type="button"
              className={`dpad-3d-btn dpad-up ${pressedDir === 'up' ? 'pressed' : ''}`}
              {...bindDpadBtn('up', 0, 1)}
              aria-label="جلو"
            >
              <IconChevron3D dir="up" active={pressedDir === 'up'} size={24} />
            </button>
            <button
              type="button"
              className={`dpad-3d-btn dpad-left ${pressedDir === 'left' ? 'pressed' : ''}`}
              {...bindDpadBtn('left', -1, 0)}
              aria-label="چپ"
            >
              <IconChevron3D dir="left" active={pressedDir === 'left'} size={24} />
            </button>
            <div className="dpad-center-hub" />
            <button
              type="button"
              className={`dpad-3d-btn dpad-right ${pressedDir === 'right' ? 'pressed' : ''}`}
              {...bindDpadBtn('right', 1, 0)}
              aria-label="راست"
            >
              <IconChevron3D dir="right" active={pressedDir === 'right'} size={24} />
            </button>
            <button
              type="button"
              className={`dpad-3d-btn dpad-down ${pressedDir === 'down' ? 'pressed' : ''}`}
              {...bindDpadBtn('down', 0, -1)}
              aria-label="عقب"
            >
              <IconChevron3D dir="down" active={pressedDir === 'down'} size={24} />
            </button>
          </div>
        )}
      </div>

      {/* RIGHT ZONE: Sculpted 3D Tactical Action Arc */}
      <div className="mc-right-arc" dir="ltr">
        {/* Auxiliary Row: Sprint Boost & Flight Mode */}
        <div className="mc-aux-row">
          <button
            type="button"
            className={`orb-btn orb-aux ${sprinting ? 'is-toggled-amber' : ''}`}
            onPointerDown={(e) => {
              e.stopPropagation();
              onToggleSprint();
            }}
            title="دویدن سریع"
          >
            <IconTurboBoots size={20} />
            <span>سرعت</span>
          </button>

          <button
            type="button"
            className={`orb-btn orb-aux ${isFlying ? 'is-toggled-cyan' : ''}`}
            onPointerDown={(e) => {
              e.stopPropagation();
              onToggleFlight();
            }}
            title="پرواز آزاد"
          >
            <IconCraneFlight size={20} />
            <span>پرواز</span>
          </button>

          {isFlying && (
            <button
              type="button"
              className="orb-btn orb-aux"
              onPointerDown={(e) => {
                e.stopPropagation();
                onSetFlyDown(true);
              }}
              onPointerUp={(e) => {
                e.stopPropagation();
                onSetFlyDown(false);
              }}
              onPointerLeave={() => onSetFlyDown(false)}
              onPointerCancel={() => onSetFlyDown(false)}
              title="فرود به پایین"
            >
              <IconChevron3D dir="down" size={18} />
              <span>پایین</span>
            </button>
          )}
        </div>

        {/* Main 3D Action Cluster: Build, Jump/Ascend, Primary Attack/Mine */}
        <div className="mc-main-cluster">
          <button
            type="button"
            className="orb-btn orb-build"
            onPointerDown={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onSecondaryTap();
            }}
          >
            <IconVoxelBuild size={28} />
            <span>{secondaryActionLabel}</span>
          </button>

          <button
            type="button"
            className="orb-btn orb-jump"
            onPointerDown={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onSetJump(true);
            }}
            onPointerUp={(e) => {
              e.stopPropagation();
              onSetJump(false);
            }}
            onPointerLeave={() => onSetJump(false)}
            onPointerCancel={() => onSetJump(false)}
          >
            <IconWingJump size={28} />
            <span>{isFlying ? 'اوج' : 'پرش'}</span>
          </button>

          <button
            type="button"
            className="orb-btn orb-primary-attack"
            onPointerDown={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onPrimaryTap();
            }}
          >
            <IconSwordPickaxe size={34} />
            <span>ضربه / کندن</span>
          </button>
        </div>
      </div>
    </>
  );
};
