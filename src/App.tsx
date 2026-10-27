import React, { useEffect, useRef, useState } from 'react';
import { FaceCustomizerModal } from './components/FaceCustomizerModal';
import { GameHud } from './components/GameHud';
import { HelpModal } from './components/HelpModal';
import { InventoryModal } from './components/InventoryModal';
import { NpcDialogModal } from './components/NpcDialogModal';
import { StartScreen } from './components/StartScreen';
import { KCraftEngine } from './engine/KCraftEngine';
import { HudState } from './types/game';

export const App: React.FC = () => {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<KCraftEngine | null>(null);
  const [hud, setHud] = useState<HudState | null>(null);

  useEffect(() => {
    if (!mountRef.current) return;
    const engine = new KCraftEngine(mountRef.current, (nextHud) => {
      setHud(nextHud);
    });
    engineRef.current = engine;

    return () => {
      engine.dispose();
      engineRef.current = null;
    };
  }, []);

  const engine = engineRef.current;

  return (
    <div className="app-shell">
      <div ref={mountRef} className="canvas-mount" />

      {hud && engine && !hud.started && hud.activeModal !== 'customizer' && (
        <StartScreen
          selectedNameFa={hud.playerNameFa}
          selectedNameKo={hud.playerNameKo}
          playerFace={hud.playerFace}
          gameMode={hud.gameMode}
          onSelectPreset={(p) => engine.selectCharacterPreset(p)}
          onToggleGameMode={() => engine.toggleGameMode()}
          onOpenCustomizer={() => engine.setModal('customizer')}
          onStartGame={() => engine.startGame()}
        />
      )}

      {hud && engine && hud.started && (
        <GameHud
          hud={hud}
          itemIcons={engine.texSys.itemIconUrls}
          onSelectHotbar={(idx) => engine.selectHotbarSlot(idx)}
          onCycleCamera={() => engine.cycleCameraMode()}
          onOpenCustomizer={() => engine.setModal('customizer')}
          onOpenInventory={() => engine.setModal('inventory')}
          onOpenHelp={() => engine.setModal('help')}
          onOpenNearbyNpc={() => engine.openNearbyNpcDialog()}
          onToggleGameMode={() => engine.toggleGameMode()}
          onToggleDayNight={() => engine.toggleDayNight()}
          onSpawnDokkaebi={() => engine.spawnDokkaebiChallenge()}
          onTeleportVillage={() => engine.teleportToVillage()}
          onMobileMove={(mx, mz, jump) => {
            engine.mobileMoveX = mx;
            engine.mobileMoveZ = mz;
            engine.mobileJumping = jump;
          }}
          onPrimaryTap={() => engine.triggerPrimaryActionTap()}
          onSecondaryTap={() => engine.triggerSecondaryAction()}
          onRotateCamera={(dy, dp) => engine.rotateCameraBy(dy, dp)}
          onSetFlyDown={(down) => { engine.mobileFlyDown = down; }}
          onSetJumping={(jumping) => { engine.mobileJumping = jumping; }}
          onToggleFlight={() => engine.toggleFlight()}
          onToggleSprint={() => engine.toggleMobileSprint()}
          onQuickGreet={(npcId) => engine.sendQuickChatToNpc(npcId, 'سلام! خوشحالم می‌بینمت.', 'سلام دوست من! به روستای ما خوش آمدی.')}
          onSetControlStyle={(style) => engine.setControlStyle(style)}
        />
      )}

      {hud && engine && hud.activeModal === 'customizer' && (
        <FaceCustomizerModal
          face={hud.playerFace}
          playerNameFa={hud.playerNameFa}
          playerNameKo={hud.playerNameKo}
          onUpdateFace={(partial) => engine.updatePlayerFace(partial)}
          onSelectPreset={(preset) => engine.selectCharacterPreset(preset)}
          onClose={() => engine.setModal(hud.started ? 'none' : 'start')}
        />
      )}

      {hud && engine && hud.activeModal === 'inventory' && (
        <InventoryModal
          hotbarIndex={hud.hotbarIndex}
          hotbar={hud.hotbar}
          inventory={hud.inventory}
          recipes={engine.getCraftingRecipes()}
          creativeItems={engine.getCreativeItems()}
          itemIcons={engine.texSys.itemIconUrls}
          gameMode={hud.gameMode}
          countItem={(id) => engine.countItem(id)}
          onSelectHotbar={(idx) => engine.selectHotbarSlot(idx)}
          onSwapWithHotbar={(invIdx) => engine.swapInventoryWithHotbar(invIdx)}
          onCraft={(recipe) => engine.craftRecipe(recipe)}
          onEquipCreative={(itemId) => engine.equipCreativeItemToHotbar(itemId)}
          onClose={() => engine.setModal('none')}
        />
      )}

      {hud &&
        engine &&
        hud.activeModal === 'npc_dialog' &&
        (hud.activeDialogNpc || hud.nearbyNpc) && (
          <NpcDialogModal
            npc={(hud.activeDialogNpc || hud.nearbyNpc)!}
            itemIcons={engine.texSys.itemIconUrls}
            gameMode={hud.gameMode}
            countItem={(id) => engine.countItem(id)}
            onTrade={(offer) => engine.executeNpcTrade(offer)}
            onToggleFollow={(entityId) => engine.toggleNpcFollow(entityId)}
            onClose={() => engine.setModal('none')}
          />
        )}

      {hud && engine && hud.activeModal === 'help' && (
        <HelpModal onClose={() => engine.setModal('none')} />
      )}
    </div>
  );
};
