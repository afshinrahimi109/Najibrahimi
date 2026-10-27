import React, { useEffect, useState } from 'react';
import { LiveChatMessage, NpcStatusSnapshot } from '../types/game';
import { IconChatBubble } from './GameIcons';

interface LiveDialogueStreamProps {
  messages: LiveChatMessage[];
  nearbyNpc: NpcStatusSnapshot | null;
  onQuickGreetNearby: (npc: NpcStatusSnapshot) => void;
  onOpenFullDialog: () => void;
}

export const LiveDialogueStream: React.FC<LiveDialogueStreamProps> = ({
  messages,
  nearbyNpc,
  onQuickGreetNearby,
  onOpenFullDialog,
}) => {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (messages.length === 0) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 120);
    return () => window.clearInterval(timer);
  }, [messages.length]);

  return (
    <div className="live-dialogue-zone">
      {/* Transient Animated Village Messages: Slide IN -> Stay -> Slide OUT off screen */}
      <div className="live-msg-stack">
        {messages.map((msg) => {
          const elapsed = now - msg.createdAt;
          const isLeaving = elapsed >= msg.durationMs;
          const pctRemaining = Math.max(
            0,
            Math.min(100, (1 - elapsed / msg.durationMs) * 100)
          );

          return (
            <div
              key={msg.id}
              className={`live-msg-card ${isLeaving ? 'is-leaving' : 'is-entering'}`}
              style={{ '--msg-accent': msg.accentColor } as React.CSSProperties}
            >
              <img
                src={msg.portraitUrl}
                alt={msg.senderFa}
                className="live-msg-avatar"
              />
              <div className="live-msg-body">
                <div className="live-msg-header">
                  <strong className="live-msg-sender">{msg.senderFa}</strong>
                  <span className="live-msg-ko">{msg.senderKo}</span>
                  <span className="live-msg-role">{msg.roleFa}</span>
                </div>
                <p className="live-msg-text">{msg.text}</p>
                <div className="live-msg-timer-track">
                  <div
                    className="live-msg-timer-fill"
                    style={{
                      width: `${pctRemaining}%`,
                      background: msg.accentColor,
                    }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Contextual Nearby Villager Interaction Strip */}
      {nearbyNpc && (
        <div className="nearby-talk-dock">
          <img
            src={nearbyNpc.portraitUrl}
            alt={nearbyNpc.preset.nameFa}
            className="nearby-dock-avatar"
          />
          <div className="nearby-dock-info">
            <strong>{nearbyNpc.preset.nameFa}</strong>
            <span>{nearbyNpc.preset.roleFa}</span>
          </div>
          <button
            type="button"
            className="nearby-quick-btn"
            onClick={() => onQuickGreetNearby(nearbyNpc)}
          >
            سلام سریع 👋
          </button>
          <button
            type="button"
            className="nearby-open-btn"
            onClick={onOpenFullDialog}
          >
            <IconChatBubble size={18} />
            <span>گفت‌وگو</span>
          </button>
        </div>
      )}
    </div>
  );
};
