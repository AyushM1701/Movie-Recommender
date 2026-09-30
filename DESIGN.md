# CineMatch visual system

The user-supplied movie interface is the visual authority for the redesign: warm black ground, cream typography, red uppercase shelf headings, teal community rating rings, a split movie feature, rich poster shelves, and a floating mobile navigation bar. CineMatch retains its own name and working movie discovery flows. Phone status chrome, TV/chat controls, fictional critic scores and social overlays are absent because those are not product capabilities.

The discovery surface is an Operate interface: the first screen presents a real catalogue film with artwork and regional watch options, followed by scrollable poster shelves. The complete catalogue has explicit era, genre, rating and sort controls with pagination; it includes films before 1970. Personal tools follow the same compact controls and spacing without inventing a separate dashboard visual language.

## Tokens

| Token | Value | Purpose |
|---|---|---|
| `--bg` | `#141310` | Warm black page ground |
| `--surface` | `#1e1d19` | Feature, dialogs, inputs |
| `--raised` | `#292721` | Provider chips and neutral controls |
| `--text` | `#f1ecd8` | Cream primary text |
| `--muted` | `#b8b4a5` | Secondary text and placeholders |
| `--line` | `#3c3930` | Quiet separation |
| `--red` | `#ee7266` | Shelf headings and accents |
| `--red-surface` | `#9b302b` | Selected controls and primary buttons |
| `--teal` | `#79c6ac` | Ratings, links, focus |
| `--radius` | `16px` | Poster and standard panel corners |
| `--shadow` | `0 20px 55px #0007` | Dialog elevation |

Manrope is the interface typeface. Anton gives the CineMatch wordmark its condensed cinema character. Body type is 14px with 1.6 line height; compact labels and provider content remain readable and contrast against their actual surfaces. Headings use at least 3:1 contrast; ordinary text and primary button states use at least 4.5:1.

The desktop content max-width is 1424px with 44px page gutters. Shelves show six posters at wide desktop sizes, five on mid desktop, and four on tablets. At mobile widths, shelves scroll horizontally while result grids use two columns. The split feature keeps text and watch information on the left and artwork on the right. Main breakpoints are 1250px, 860px and 540px. Bottom navigation at mobile sizes reserves safe-area space; expanded navigation is a body-level viewport drawer.

Every actionable control has a 44px minimum target. Focus uses a 2px teal outline with 4px offset. Dialog layers isolate background content with inert, expose only the topmost `aria-modal`, restore the launching focus, and close by Escape. Genre toggles update in place with `aria-pressed`; autocomplete has arrow-key/Enter selection and a live result announcement. Nonessential animation and smooth scrolling are disabled by `prefers-reduced-motion`.

Watch information belongs below every rendered movie card and in details, including library rows and list items. It distinguishes available providers, no regional listing and temporary lookup failure. Provider content has attribution and checked dates when supplied. Ratings represent the TMDB community on a ten-point scale; unknown ratings display a dash rather than a fabricated value.

Functional checks live in `frontend/tests/*.test.mjs`. Root integration verifies desktop/mobile rendering and native browser keyboard/focus behavior using a disposable account and database; the lightweight DOM test harness does not certify browser geometry or accessibility.
