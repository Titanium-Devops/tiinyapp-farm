# Style lock: tiinyapp.farm

Locked: 2026-09-12. Grounded in the approved hero painting (site/assets/hero.jpg) and Jason's sprout mark (brand/tiinyapp-farm-square-logo.png). Mood: warm, dark-only.

## Color contract
text #E8EEF2 · bg #090D14 · surface #12171F · border #1E2732 · primary (hay) #F2C462 · on-primary #090D14 · accent (cyan) #00C8F0 · mint #7FE3DC (chips, verified) · mute #9AA7B4 · error #E5533D / #F0A08F
Text-safe (>=4.5): text/bg, text/surface, text/border, primary/on-primary, accent/on-primary, bg/primary, surface/primary, bg/accent, surface/accent, primary/border, accent/border.
Decorative only: text/primary, text/accent, primary/accent, bg/surface, surface/border. Never text on hay or cyan; hay and cyan never touch.
Accent budget: hay for the one primary action per view and the current step; cyan for links and glow only; under 5% of any viewport.

## Type
Fraunces 700 (opsz 144): h1 40/1.1, app names 22/1.2. Nunito: body 16/1.55, small 14/1.5, label 13/1.4 600. Mono (SF Mono, Menlo): commands, hashes, ids, 14/1.6. Three families, no italics in headings.

## Space
4 px base. Scale 4 8 12 16 24 32 48 64 96 128. Card padding 20, gap between cards 20 (padding never exceeds gap). Tool pages: section gap 48; home: hero to shelf 64, shelf to submit band 96.

## Shape and depth
Radius 12 on tiles and inputs, 999 on buttons and chips. Hairline borders (#1E2732), no shadows except a 0 0 0 1px ring on focus and a soft glow behind app art.

## Layout
Content width 1040 desktop, 16 px gutters at phone. Home: shelf grid auto-fill min 300. Tool pages: single column 720. App page: 1fr + 300 rail, one column under 760.

## Motion
150 ms ease-out on state changes; one 300 ms rise on the shelf tiles at load; no hover scale; reduced motion drops to opacity.

## Assets
Icons: Tabler via Iconify, stroke 1.75, tinted #9AA7B4 (design/assets/icons). App art: every app has icon (1024 square, transparent) and header (3:2) in the sprout family; generated with gpt-image-2 where the maker supplied none, replaced by the maker's own on update. Share cards from scripts/share-cards.py.

## Do not
- Equal-weight grey cards. Three columns for a sequence. Emoji. Farm nouns in instructions. Gradients on buttons or text.
