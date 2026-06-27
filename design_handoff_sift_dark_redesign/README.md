# Handoff: Sift — Dark Redesign (xAI canvas + lobe-ui language)

## Overview
A full visual redesign of the Sift iOS app (SwiftUI). Sift captures a concept the user
just heard, generates a note, and lets the user deepen it through a per-concept chat.
This redesign moves the whole app to a **single dark canvas with one blue accent**,
adopts the **lobe-ui visual language** (rounded "block" cards, soft shadows, translucent
fills, Geist type, lucide stroke icons, real provider brand marks), keeps the existing
**Sift particle logo**, and replaces the old segmented tab bar with a **floating native
tab bar**. Seven screens are specified.

## About the Design Files
The file in this bundle — `Sift Redesign.dc.html` — is a **design reference created in
HTML**. It is a prototype showing the intended look, layout, and a couple of micro-states
(streaming cursor, selected provider). **It is not production code to copy.** The task is
to **recreate these designs in the existing SwiftUI codebase** (`ios/Sift/…`) using its
established patterns: `SiftTheme`, the existing `Color`/`Font` helpers, SF Symbols or a
bundled icon set, and the existing API/view-model layer. Do not embed a web view; rebuild
each screen as native SwiftUI.

Open the HTML file in a browser. It is a horizontal "canvas" of 7 phone frames; pan to see
all of them. Each frame is labeled (01 Record … 07 Provider picker).

## Fidelity
**High-fidelity.** Final colors, type ramp, spacing, radii, and component structure are all
intentional — match them. Exact hex/measurements are in **Design Tokens** below. Reproduce
the layouts pixel-faithfully, then wire to the existing data layer.

---

## Design Tokens

### Color
| Token | Hex / value | Use |
|---|---|---|
| `canvas` | `#0A0B0D` | App background, every screen |
| `deviceBezel` | `#040405` | (mock only — phone bezel, ignore in app) |
| `surface` (card) | `#16181C` | Block cards, grouped setting cards |
| `surfaceSoft` | `rgba(255,255,255,0.05)` | Search field, inputs, chips, secondary button |
| `surfaceSoftHi` | `rgba(255,255,255,0.07)` | Active tab pill, user chat bubble |
| `hairline` | `rgba(255,255,255,0.07)` | Card borders, dividers (solid form: `#1C1E22`) |
| `hairlineSoft` | `rgba(255,255,255,0.06)` | Inner dividers inside cards |
| `accent` | `#3D7FFF` | The single accent — primary buttons, active nav, links, selection, streaming cursor, icon tiles |
| `accentWash` | `rgba(61,127,255,0.12)` | Accent icon-tile fill, "Saved to note" chip, success alert |
| `accentBorder` | `rgba(61,127,255,0.20)` | Border on accent washes |
| `accentTextOnWash` | `#9CC0FF` | Text/label on an accent wash |
| `textPrimary` | `#F3F4F5` | Titles, body emphasis |
| `textSecondary` | `#C7CACE` | Note body |
| `textBody` | `#ABAFB6` | Secondary body, tag text |
| `textMuted` | `#8B8F96` | Card descriptions |
| `textFaint` | `#74787E` / `#71757C` | Captions, inactive tab labels, property labels |
| `textFaintest` | `#5B5E63` / `#4F5258` | Mono micro-labels, timestamps |
| `white` | `#FFFFFF` | Provider brand-icon chips, send-button glyph |

There is **no second accent color**. Orange/teal/etc. appear **only** inside provider brand
logos (see Assets). Status, selection, success — all use the one blue.

### Typography
- **Sans:** Geist (fallback: SF Pro / system). The app already targets iOS — use **SF Pro**
  if Geist isn't bundled; the ramp below is what matters.
- **Mono:** Geist Mono (fallback: SF Mono / `ui-monospace`). Used for ALL-CAPS micro-labels
  and technical values (URLs, keys, model ids).

| Role | Size / weight / spacing |
|---|---|
| Screen title (Library, Profile) | 30, 700, `-0.8px` |
| Large hero (Record) | 26, 600, `-0.5px`, line-height 33 |
| Page title (Concept note) | 27, 700, `-0.6px` |
| Nav title (centered) | 16, 600, `-0.3px` |
| Card title | 15–16, 600 |
| Body / note | 15, 400, line-height 24–25 |
| Card description | 13, line-height 18 |
| Tag / chip | 11, 400 |
| Mono section eyebrow | 11, CAPS, `+0.6px`, color `textFaint` (e.g. `RUNTIME`, `ALL CONCEPTS`) |
| Mono field label | 10, CAPS, `+0.5px`, color `textFaintest` (e.g. `BASE URL`) |
| Tab bar label | 10, 500 |

### Spacing & layout
- Screen horizontal padding: **20px** (Library/Profile/Provider/Note), 18px (Chat), 24px (Record).
- Card interior padding: **14–16px**. Gap between stacked cards: **10px**.
- Grouped-setting rows: 14–15px vertical padding, inner divider inset by the row padding.
- Status-bar height 54px; nav row 50px; floating tab bar lives 18px from bottom.

### Radius
| Element | Radius |
|---|---|
| Block card | 16px |
| Grouped setting card | 16px |
| Icon tile (concept/provider) | 10–14px |
| Button | 12–13px |
| Search field / input bar | 12–18px |
| Tag / select chip | 7–9px |
| Floating tab bar | 26px; active item pill 20px |
| Bottom sheet | 26px top corners |
| Sift send button | 12px (rounded square, **not** a circle) |

### Shadow / elevation
- Block cards: `0 1px 2px -1px rgba(0,0,0,.5), 0 6px 16px -10px rgba(0,0,0,.5)`.
- Floating tab bar: `0 10px 34px -12px rgba(0,0,0,.7)` + backdrop blur (`ultraThinMaterial` dark).
- Primary "Save" button: subtle accent glow `0 6px 18px -8px rgba(61,127,255,.7)`.
- Bottom sheet: `0 -26px 50px -16px rgba(0,0,0,.7)`.
- No other shadows. Elevation is carried by the hairline border + fill step.

A ready-to-paste `SiftTheme` translation of these tokens is included:
**`SiftTheme.suggested.swift`**.

---

## Global components

### Floating tab bar (replaces the old segmented control)
- A pill container floating 18px above the home indicator, full width minus 16px each side,
  height 66px, `rgba(20,22,26,0.72)` + dark blur, 1px `rgba(255,255,255,0.08)` border,
  radius 26px.
- Three items: **Capture** (lucide `plus` inside a 30px accent rounded-square tile),
  **Library** (lucide `library`/book icon), **Profile** (lucide `user`).
- The **active** item sits on a 20px-radius `surfaceSoftHi` pill; its label is `textPrimary`
  500, inactive labels are `textFaint`. The Capture icon tile is always accent-filled; when
  Capture is the active tab the surrounding pill is shown.
- Order on each screen: Record→Capture active, Library→Library active, Profile→Profile active.

### Block card
`surface` fill, 1px `hairline` border, 16px radius, card shadow. The universal container for
concept cards, setting groups, the user card, and alerts.

### Icon tile
A rounded-square (10–14px radius) holding a single glyph. Two variants:
- **Accent tile:** `accentWash` fill + `accentBorder`, glyph in `accent`. Used for the
  focused/primary concept (e.g. Semantic Cache) and the note hero.
- **Neutral tile:** `surfaceSoft` fill + hairline, glyph in `textBody`.

### Tag / select chip
`surfaceSoft` fill, 1px hairline, 7–9px radius, 11–13px `textBody` text. Used for tags and
property values. The "All" filter chip when selected is **accent-filled, white text**.

### Buttons
- **Primary:** accent fill, white label+glyph, 13px radius, 48px tall (e.g. "Save changes",
  with accent glow). 44px in the diagnostics row ("Test model").
- **Secondary:** `surfaceSoft` fill, 1px `rgba(255,255,255,0.1)` border, `textSecondary`
  label (e.g. "Load models", "Web search").

---

## Screens / Views

> Map to existing files under `ios/Sift/`. Names below are the redesign's; match them to the
> current view files (`RecordView.swift`, plus Library/Concept/Profile/Settings views).

### 01 · Record  (`RecordView`)
- **Purpose:** capture a new concept.
- **Layout:** top-left wordmark row (24px Sift particle logo + "Sift" 20/600). Centered hero:
  98px Sift logo, then "What new concept did you hear?" (26/600/-0.5) and subtitle
  "Capture it now. Deepen it later." (15, `textFaint`). Bottom: a capture input bar, then the
  floating tab bar.
- **Capture input bar:** `surfaceSoft` fill, 1px `rgba(255,255,255,0.09)`, 18px radius;
  left lucide `circle-plus`, placeholder "Capture a concept…" (`#5E6166`), a lucide `mic`
  glyph, and a 40px **accent rounded-square** send button with an up-arrow.

### 02 · Library  (`LibraryView`)
- **Purpose:** browse all captured concepts.
- **Layout:** title "Library" (30/700) with a 38px `surfaceSoft` rounded-square **+** button
  on the right. Search field (`surfaceSoft`, lucide search, "Search concepts & tags").
  Filter row: **All** (accent-filled) · Workflow · Research (`surfaceSoft` chips, 9px radius).
  Mono eyebrow `ALL CONCEPTS  30`. Then a vertical stack (gap 10) of concept Block cards.
- **Concept card:** icon tile (accent tile for the focused concept, neutral otherwise) +
  title (15/600) + right-aligned mono timestamp (`NOW`, `2D`); one-line description
  (13/`textMuted`); a row of tag chips. Example data in the mock: Semantic Cache (database
  icon, AI/caching/LLM), Vector Database Indexing (box icon), Reranking (shuffle/convert
  icon, slightly emphasized as last-opened).

### 03 · Concept · Chat  (`ConceptChatView`)
- **Purpose:** deepen a concept by asking follow-ups; answers fold back into the note.
- **Layout:** nav row — back (rounded-square tile), centered concept title "Semantic Cache",
  edit (pencil) tile. Below: a **model chip** (Sift particle mark + "deepseek · sift-explain"
  + chevron) in a `surfaceSoft` 12px-radius pill. Then the conversation:
  - **User message:** right-aligned, `surfaceSoftHi` bubble, 16px radius (tail corner 16/6),
    15/lh22, `textPrimary`.
  - **Assistant (Sift) message:** left, a sender row (18px Sift mark, "Sift" 13/600, ·,
    mono `deepseek-v4-flash`), then body 15/lh25 `textSecondary`. Inline emphasis words use
    `accent`; quoted strings use `textBody`. A **blinking accent caret** (8×17, 2px radius)
    trails the streaming text (1s `steps(1)` blink). After completion show a
    "Saved to note" chip (accent wash, check glyph).
- **Composers:** a "Reply to Sift…" input bar (same style as Record's, accent send button)
  sits just above the floating tab bar.

### 04 · Concept · Note  (`ConceptNoteView` / overview)
- **Purpose:** the structured note view of a concept (Notion-like property page, restyled dark).
- **Layout:** nav row — back tile; right side share + overflow tiles. Body:
  48px **accent icon tile** (concept glyph), title "Semantic Cache" (27/700/-0.6).
  **Property rows** (label column 88px, lucide icon + `textFaint` label; value = chips):
  Maturity → `Growing` (accent-wash chip), Status → `Ready` (neutral chip),
  Topics → multi chips, Tags → multi chips. Then a **callout block** (a Block card with a
  lucide `lightbulb` accent glyph + the one-line definition). Then a "Why it matters" heading
  (17/600) + paragraph (15/lh24). Then a **related-concept row** (link icon + "Vector
  Database Indexing" + chevron) on a `surfaceSoft` 12px row.

### 05 · Profile  (`ProfileView`)
- **Purpose:** account, runtime config entry points, diagnostics, privacy.
- **Layout:** title "Profile" (30/700). **User card** (Block card): 46px accent tile with the
  Sift mark, "Sift User" (16/600), "development" (13/`textFaint`), chevron.
  - Mono eyebrow `RUNTIME` → grouped card with two rows: **Model Provider** (lucide chip icon
    + label; value = DeepSeek brand mark in a 18px white chip + "deepseek" mono + chevron) and
    **Web Search** (globe icon; value "ddgs" mono + chevron).
  - Mono eyebrow `DIAGNOSTICS` → a two-button row: **Test model** (primary accent, lucide
    flask/test glyph) + **Web search** (secondary, globe). Below, a **success alert**
    (accent-wash Block): check glyph + "Sift runtime model responded." + mono
    "deepseek · deepseek-v4-flash".
  - Mono eyebrow `PRIVACY` → a `surfaceSoft` info block (lock glyph + the masked-key note).

### 06 · Model Provider  (`ModelProviderSettingsView`)
- **Purpose:** configure the active provider.
- **Layout:** centered nav title "Model Provider" with back tile. Mono eyebrow
  `CONFIGURATION` → a grouped Block card:
  - **Provider** row: label + value chip (DeepSeek brand mark in white chip + "DeepSeek") + chevron.
  - **BASE URL** field (mono label + `https://api.deepseek.com/v1` mono value).
  - **API KEY** field (mono label + `•••••••••••• 76f7`, `textFaint`).
  - **MODEL** field (mono label + `deepseek-v4-flash` + a lucide list/lines affordance).
  Then two stacked buttons: **Load models** (secondary) and **Save changes** (primary accent
  with glow).

### 07 · Provider picker  (bottom sheet from the Provider row)
- **Purpose:** choose the model provider.
- **Layout:** dimmed scrim over screen 06; a bottom sheet (`#131418`, 26px top radius, grab
  handle). Header "Select Provider" (17/600) + a circular close (× ) button. A list of rows,
  each = white **brand-icon chip (34px)** + name (15/500) + one-line description (12/`textFaint`):
  Alibaba DashScope, Anthropic, Arcee AI, **DeepSeek (selected)**, GMI Cloud, OpenRouter.
  The **selected** row sits on an `accentWash` 12px-radius highlight with `accentBorder` and a
  trailing accent check; its description uses `accentTextOnWash`.

---

## Interactions & Behavior
- **Tabs:** Capture / Library / Profile switch root views. Capture is the default landing.
- **Capture submit:** sending text (or the mic) creates a concept and kicks off note
  generation. Show an in-progress state on the new concept (the existing generating state) —
  the mock doesn't redraw it but the data layer already supports it; keep that behavior.
- **Concept open:** tapping a Library card opens the concept. The redesign has two faces of a
  concept — the **Chat** (03) and the **Note** (04). Keep whatever navigation the current app
  uses between them (e.g. a segmented/“Chat | Note” toggle or push); the visual targets are 03/04.
- **Follow-up send:** appends a user bubble, streams a Sift answer (blinking caret during
  stream), then shows "Saved to note" once merged into the note.
- **Provider row tap (Profile or Model Provider):** presents the **Provider picker** sheet
  (07). Selecting a provider updates the active provider, dismisses, and the Provider value
  chip + brand mark update everywhere (Profile row, Model Provider config).
- **Load models:** fetches the model list for the chosen provider (existing API). **Save
  changes:** persists config. Keep the existing masked-key behavior (server stores the key,
  iOS only ever sees `••• last4`).
- **Test model / Test web search:** run the existing diagnostics; on success render the
  accent-wash success alert with provider · model.
- **Streaming caret:** 1s `steps(1)` blink (opacity 1↔0). No other looping animation.
- Transitions: standard iOS push for detail; sheet for the picker. Keep motion restrained.

## State Management
Reuse the existing view models / API client (`SiftAPIClient`, `MockSiftAPIClient`). No new
data model is introduced by this redesign — it is a presentation change. State surfaces the
mock relies on:
- `concepts: [Concept]` with `title`, one-line `summary`, `tags`, `topics`, `maturity`
  (Initial/Growing/Mature), `status` (e.g. Ready), `updatedAt` (→ relative `NOW`/`2D`/`1W`).
- per-concept `messages: [ChatMessage]` (role, text, `mergedIntoNote: Bool`).
- `runtime`: active `provider` (id + display name + brand icon key), `model`, masked
  `apiKeyPreview`, `baseURL`, `webSearchProvider` ("ddgs").
- `providers: [Provider]` for the picker (id, name, description, brand icon key, `selected`).
- diagnostics result (`success`, `provider`, `model`, message).

## Assets
- **Sift particle logo:** already in the repo (`ios/Sift/App/SiftLogo.swift`) — keep it. The
  mock recolors the particles to `accent`/neutral grays on dark; reproduce that tint.
- **Icons:** the mock uses **lucide** stroke icons. In SwiftUI prefer **SF Symbols** with the
  closest match (plus, library/books.vertical, magnifyingglass, person, arrow.up, mic,
  chevrons, link, lightbulb, lock, globe, square.and.arrow.up, ellipsis, pencil, slider/list).
  Keep them monochrome, ~1.6–1.8pt stroke equivalent, never filled except where noted.
- **Provider brand marks:** **bundled in `icons/`** (sourced from **lobe-icons**,
  https://github.com/lobehub/lobe-icons), rendered on **white rounded chips**:
  `icons/deepseek.svg` (blue), `icons/anthropic.svg` (black A), `icons/alibabacloud.svg`
  (orange), `icons/arcee.svg` (teal), `icons/openrouter.svg` (black). **GMI Cloud** has no
  lobe-icons mark — `icons/gmicloud.svg` is a clean "GMI" wordmark placeholder; swap in the
  official GMI mark if you have it. Import these into the app's asset catalog (or an icon set)
  keyed by `provider.brandIconKey`. Each is 24×24 (gmicloud 48×48), already self-contained.
  Always present them on a white chip so the colored/near-black marks stay legible on the
  dark canvas (the active provider also appears as a small ~18px white chip in the Profile
  and Model Provider rows).

## Files
- `Sift Redesign.dc.html` — the high-fidelity design reference (7 phone frames on one canvas).
- `SiftTheme.suggested.swift` — a direct SwiftUI translation of the Design Tokens above
  (colors, radii, type ramp, shadows). Reconcile with the existing `ios/Sift/App/SiftTheme.swift`.
- `icons/` — provider brand SVGs (deepseek, anthropic, alibabacloud, arcee, openrouter,
  gmicloud) ready to import into the asset catalog.

### Existing repo touch-points (branch `codex/sift-mvp`)
- `ios/Sift/App/SiftTheme.swift` — replace/extend with the dark token set.
- `ios/Sift/App/SiftLogo.swift` — keep; apply accent tint.
- `ios/Sift/Record/RecordView.swift` — screen 01.
- Library / Concept (chat + note) / Profile / Model-Provider-settings views — screens 02–07.
- Root tab container — swap to the floating tab bar.
- `ios/Sift/API/*` — unchanged; this is presentation-only.
