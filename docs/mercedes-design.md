# Mercedes-Benz Corporate Identity / Corporate Design

NTF Insight is intended for use in a Mercedes-Benz engineering environment. The desktop UI therefore follows a restrained, technical visual direction based on **black, white, silver/graphite, clear hierarchy and high contrast**.

The authoritative source for exact brand usage is the Mercedes-Benz **Brand Design System (BDS)** available to the project through the approved company channel. Public Mercedes-Benz material also points to the BDS as the source for brand guidelines and assets.

## Rules for NTF Insight

- Use a minimal black/white/graphite visual language.
- Prioritize legibility and engineering information density over decorative effects.
- Light mode must use dark text on white/light surfaces.
- Dark mode must use light text on dark/black surfaces.
- Use subtle silver/graphite borders and selections rather than saturated accent colors.
- Do not embed or redistribute proprietary Mercedes-Benz font files in the repository.
- Do not add the Mercedes-Benz star/logo unless the project has approved brand assets and usage rights from the internal BDS.
- If an approved corporate font is available on the target workstation, it can be configured locally; the repository keeps safe system-font fallbacks.
- Internal BDS tokens, spacing rules, logo clear-space and exact approved colors take precedence over the fallback values in this repository.

## Current fallback palette

The app currently uses a brand-compatible neutral fallback, not a claim of exact official BDS tokens.

### Light

- page background: very light grey
- surfaces: white
- primary text: near black
- secondary text: graphite
- borders/selections: silver/grey
- sidebar: black/graphite

### Dark

- page background: near black
- surfaces: graphite
- primary text: near white
- secondary text: light silver
- borders/selections: medium graphite
- sidebar: deeper black

## Typography

NTF Insight now resolves Mercedes-Benz corporate typography at runtime without redistributing font binaries.

Preferred mapping:

- **Corpo S Title/Text** for UI text, tables, controls, buttons and body copy.
- **Corpo A Title/Text Condensed** for major headings.
- Historical/system family names such as **Corporate S** and **Corporate A** are also detected for compatibility.
- Segoe UI / Arial remain safe fallbacks when the corporate fonts are unavailable.

The app checks installed system font families automatically. It also supports an approved internal font directory through:

```powershell
$env:NTF_INSIGHT_FONT_DIR = "C:\approved\mercedes-fonts"
python -m ntf_insight
```

If the internally approved family names differ from the historical Corporate A/S names, they can be selected explicitly:

```powershell
$env:NTF_INSIGHT_BODY_FONT_FAMILY = "Approved Body Family"
$env:NTF_INSIGHT_HEADING_FONT_FAMILY = "Approved Heading Family"
python -m ntf_insight
```

Font binaries are intentionally not committed to Git. Current public brand guidance states that the Mercedes-Benz brand fonts are obtained through the Brand & Design Navigator and require administrator approval; the internal/current Brand Design System and its licensing/asset distribution rules remain authoritative.

## Accessibility / readability

Contrast is a functional requirement for this engineering tool:

- white/light surfaces always receive dark text
- dark surfaces always receive light text
- table selections keep readable foreground/background contrast
- inputs, combo boxes, menus and headers explicitly define both foreground and background colors
- both themes are covered by automated style tests

## Internal BDS integration

When access to the project-approved BDS tokens/assets is available, replace only the theme tokens in `src/ntf_insight/app/styles.py`. The application structure and widgets should not need redesigning.
