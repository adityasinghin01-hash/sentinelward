# Shared frontend foundation

Import controls from `components/ui.tsx`. Existing exports remain supported; `extra.tsx` re-exports the Radix `Dialog` for existing callers.

- `Button`: `variant="primary|secondary|ghost|danger|icon"`, `size={36|40|44}`, `pending`. Use primary for Acknowledge, 44 for primary clinical actions, and danger for destructive confirmations. Pending disables duplicate submission and keeps intrinsic width.
- `StateChip state={verdict}`: all eight API verdicts plus `NO_DATA`/`null`; canonical words, icon, semantic colour. `stateChips` exports the mapping.
- `Chip`, `Card`, `Panel`, `EmptyState`, `Skeleton` are neutral surfaces/feedback.
- `SegmentedControl`: controlled `value`, `onChange`, `options`, `label`; Radix RadioGroup. Existing `Tabs` retains its tested toggle-button semantics.
- `Switch`: controlled `checked`, `onCheckedChange`, visible `label`; Radix Switch. `Menu`, `MenuItem`, `MenuCheckboxItem`, `MenuLabel`, `MenuSeparator` wrap Radix DropdownMenu.
- `Tooltip` takes one element child and `text`; the App provides 500/300 ms timing. `Tip` preserves existing accessible descriptions and works when rendered outside App.
- `Dialog` keeps the old `open/title/children/onClose/actions` contract with Radix trapping/scroll lock. `ConfirmDialog` takes `open/title/bed/monitor/consequence/onClose/onConfirm`, optional `actionLabel/pending`; Radix AlertDialog initially focuses Cancel.
- `toast` is Sonner, mounted once by App via `Toaster`. Routine 5000 ms; pass `{duration:8000,action:{label:'Undo',onClick}}` for an Undo prompt after API success.

`ThemeToggle` is shared by all routes. `lib/theme.ts` exports `useTheme`, `useThemeTokens`, `readThemeTokens`, `initializeTheme`, `applyTheme`; the `sw-theme-change` window event carries `{theme}`. Waveform/TrendChart use the hook and retain their sample/frozen logic. Theme preference is `localStorage['sw.theme']`, with storage failures tolerated.

CSS imports are fixed: tokens, base, components, app, ward, bed, pages, landing, login. Colours belong only in tokens.css; page builders own their named CSS file. Root `<html data-theme>` controls both themes; no navy aliases remain. The development-only `/dev/ui` route is excluded from production.
