# Third-party notices

narovva bundles the following third-party files. Each keeps its own license.

| What | Where | License |
|---|---|---|
| [GSAP](https://gsap.com) 3.14.2 | `src/narovva/motion/templates/reel/vendor/gsap.min.js` | GreenSock [Standard "No Charge" License](https://gsap.com/standard-license) (see the file header) |
| [three.js](https://threejs.org) r149 (0.149.0) | `src/narovva/motion/templates/reel/vendor/three.min.js` | MIT, Copyright 2010-2023 Three.js Authors (see the file header) |
| [Lucide](https://lucide.dev) icons (some derived from [Feather](https://feathericons.com)) | `src/narovva/motion/templates/reel/icons.js` | ISC, and MIT for the Feather-derived icons (full text in the file header) |
| Archivo Black, Inter, JetBrains Mono (via [Fontsource](https://fontsource.org)) | `src/narovva/motion/templates/reel/fonts/` | SIL Open Font License 1.1 (`fonts/OFL.txt`) |
| DejaVu Sans | `assets/fonts/` | Bitstream Vera Fonts license with DejaVu changes in the public domain (`assets/fonts/LICENSE`) |

Adapted ideas (no code copied):

- Hook formulas in `src/narovva/hooks/formulas.yaml` and the "multiple of the
  channel's median" performance method are adapted from
  [youtube-agent-skill](https://github.com/Jakeschincariol/youtube-agent-skill) (MIT).

Installed at build time, not bundled: [HyperFrames](https://github.com/heygen-com/hyperframes)
(npm, pinned in `package.json`) and the Python packages in `pyproject.toml`, each under
its own license.

The Context Unfiltered name and logo (`assets/logo/CU.png`) belong to the Context
Unfiltered channel and are not covered by this repository's license.
