# GraphBloom demo site

Static Next.js site (3D graph, story sequence, results). Data lives in `public/data/` and is written by `scripts/export_demo.py` from the repo root.

```bash
npm install
npm run dev      # http://localhost:3000
npm run build    # static export to out/
```

Add `?fps` to the URL for a frame-rate readout, and `?slow=4` to play the hero at quarter speed.

## Deploy to Vercel

Project root is `demo/`. Framework preset: Next.js (auto-detected); no environment variables.

CLI:

```bash
cd demo
npx vercel login
npx vercel --prod     # accept the defaults; "link to existing project" can be no
```

Dashboard: Add New Project, import the GitHub repo, set Root Directory to `demo`, Deploy. Pushing the `dev` branch gives a preview URL; production follows the branch set as Production Branch (Settings, Git).

## Refresh the data

```bash
.venv/bin/python scripts/cost_projection.py   # results/cost_projection.json, $0
.venv/bin/python scripts/export_demo.py       # needs HydraDB running with learned_iter5 restored
```
