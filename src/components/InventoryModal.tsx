import React, { useState } from 'react';
import { getItemMeta } from '../data/items';
import {
  CraftingRecipe,
  GameMode,
  InventoryItemId,
  InventorySlot,
} from '../types/game';

interface Props {
  hotbarIndex: number;
  hotbar: Array<InventorySlot | null>;
  inventory: Array<InventorySlot | null>;
  recipes: CraftingRecipe[];
  creativeItems: InventoryItemId[];
  itemIcons: Record<string, string>;
  gameMode: GameMode;
  countItem: (id: InventoryItemId) => number;
  onSelectHotbar: (idx: number) => void;
  onSwapWithHotbar: (invIdx: number) => void;
  onCraft: (recipe: CraftingRecipe) => void;
  onEquipCreative: (itemId: InventoryItemId) => void;
  onClose: () => void;
}

export const InventoryModal: React.FC<Props> = ({
  hotbarIndex,
  hotbar,
  inventory,
  recipes,
  creativeItems,
  itemIcons,
  gameMode,
  countItem,
  onSelectHotbar,
  onSwapWithHotbar,
  onCraft,
  onEquipCreative,
  onClose,
}) => {
  const [tab, setTab] = useState<'craft' | 'catalog'>('craft');

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card inventory-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>کیف ابزار و میز ساخت‌وساز (제작대)</h2>
            <p className="modal-subtitle">
              اسلات فعال نوار ابزار: شماره {hotbarIndex + 1} — روی آیتم‌های کیف کلیک کن تا جابجا بشن
            </p>
          </div>
          <button className="close-btn" onClick={onClose}>
            ✕ بستن (E)
          </button>
        </div>

        <div className="tab-bar">
          <button
            className={`tab-btn ${tab === 'craft' ? 'active' : ''}`}
            onClick={() => setTab('craft')}
          >
            ⚒️ ساخت‌وساز و کوله‌پشتی
          </button>
          <button
            className={`tab-btn ${tab === 'catalog' ? 'active' : ''}`}
            onClick={() => setTab('catalog')}
          >
            🏯 کاتالوگ همه بلوک‌های ماین‌کرفت و کره‌ای
          </button>
        </div>

        {tab === 'craft' ? (
          <div className="inv-two-col">
            {/* Crafting Column */}
            <div className="craft-list-col">
              <div className="field-title">دستورهای ساخت‌وساز (کلیک برای ساخت):</div>
              <div className="recipe-scroll">
                {recipes.map((r) => {
                  const canCraft =
                    gameMode === 'creative' ||
                    r.ingredients.every((ing) => countItem(ing.id) >= ing.count);
                  return (
                    <button
                      key={r.id}
                      className={`recipe-row ${canCraft ? 'craftable' : 'locked'}`}
                      onClick={() => onCraft(r)}
                    >
                      <img
                        src={itemIcons[String(r.resultId)]}
                        alt={r.nameFa}
                        className="slot-icon-sm"
                      />
                      <div className="recipe-info">
                        <strong>{r.nameFa}</strong>
                        <div className="ing-tags">
                          {r.ingredients.map((ing, i) => {
                            const have = countItem(ing.id);
                            const meta = getItemMeta(ing.id);
                            return (
                              <span
                                key={i}
                                className={have >= ing.count || gameMode === 'creative' ? 'ok' : 'need'}
                              >
                                {meta.nameFa}: {have}/{ing.count}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                      <span className="craft-badge">{canCraft ? 'ساخت +' : 'کمبود'}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Backpack Grid */}
            <div className="backpack-col">
              <div className="field-title">کوله‌پشتی شما (کلیک برای انتقال به دست فعال):</div>
              <div className="inv-grid-18">
                {inventory.map((slot, idx) => {
                  const meta = slot ? getItemMeta(slot.id) : null;
                  return (
                    <button
                      key={idx}
                      className="inv-cell"
                      title={meta ? `${meta.nameFa} (${meta.nameKo})` : 'خالی'}
                      onClick={() => onSwapWithHotbar(idx)}
                    >
                      {slot && (
                        <>
                          <img src={itemIcons[String(slot.id)]} alt={meta?.nameFa} />
                          {slot.count > 1 && <span className="cell-count">{slot.count}</span>}
                        </>
                      )}
                    </button>
                  );
                })}
              </div>

              <div className="field-title" style={{ marginTop: 14 }}>
                نوار ابزار پایین صفحه (اسلات مقصد را انتخاب کن):
              </div>
              <div className="inv-hotbar-preview">
                {hotbar.map((slot, idx) => {
                  const meta = slot ? getItemMeta(slot.id) : null;
                  return (
                    <button
                      key={idx}
                      className={`inv-cell ${hotbarIndex === idx ? 'selected-slot' : ''}`}
                      onClick={() => onSelectHotbar(idx)}
                    >
                      <span className="slot-num-mini">{idx + 1}</span>
                      {slot && (
                        <>
                          <img src={itemIcons[String(slot.id)]} alt={meta?.nameFa} />
                          {slot.count > 1 && <span className="cell-count">{slot.count}</span>}
                        </>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        ) : (
          <div className="catalog-pane">
            <p className="catalog-hint">
              روی هر بلوک، ابزار یا غذای کره‌ای کلیک کن تا مستقیماً در اسلات شماره{' '}
              <strong>{hotbarIndex + 1}</strong> دستت قرار بگیرد:
            </p>
            <div className="catalog-grid">
              {creativeItems.map((id) => {
                const meta = getItemMeta(id);
                return (
                  <button
                    key={String(id)}
                    className="catalog-item-btn"
                    onClick={() => onEquipCreative(id)}
                  >
                    <img src={itemIcons[String(id)]} alt={meta.nameFa} />
                    <strong>{meta.nameFa}</strong>
                    <span>{meta.nameKo}</span>
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
