# Share-card fonts

The Phase 5b environment could not resolve `api.github.com` or
`fonts.googleapis.com`, and no local Fraunces or Nunito files were available.
The following authentic DejaVu fallbacks are bundled, as allowed for card
rendering by `docs/PHASE-5B.md`:

| Files | Family | Weight | Intended card use |
| --- | --- | --- | --- |
| `DejaVuSerif-Bold.ttf`, `DejaVuSerif-Bold.woff2` | DejaVu Serif | 700 | Seed/maker name (Fraunces fallback) |
| `DejaVuSans.ttf`, `DejaVuSans.woff2` | DejaVu Sans | 400 | Pitch, biography and attribution (Nunito fallback) |

TTFs were copied unchanged from the installed LibreOffice headless runtime's
`Contents/Resources/fonts/truetype/` directory. WOFF2 files were converted from
those TTFs using already-installed FontTools and Brotli; no build or runtime
dependency was added. The complete bundled DejaVu license section from that
runtime is in `LICENSE-DejaVu.txt`.

These files are intentionally named DejaVu; they are not Fraunces or Nunito.
The browser may continue loading the actual brand fonts through its existing
Google Fonts stylesheet. Once official assets are available, place licensed
`Fraunces.ttf`, `Nunito.ttf`, `Fraunces.woff2`, and `Nunito.woff2` here and use
those for locally hosted brand typography.

TTF SHA-256:

- `DejaVuSerif-Bold.ttf`: `c47b5527bcdc8dcf9ea8c77054454c5a884beaca2f44851a2a823ee639cbf07f`
- `DejaVuSans.ttf`: `7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954`
