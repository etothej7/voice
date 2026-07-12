# Rep Performance UI

Manager-facing view of call scorecards produced by `../analysis/pipeline.py`.
Stack mirrors `optimus_front_end` (Vite + React 19 + TS, Tailwind v4, shadcn-style
components, TanStack Query, react-router v7) so pages/components can be moved
over directly — `src/components/ui/*`, `src/lib/{utils,theme,queryClient}.*` are
verbatim copies from that repo.

```sh
npm install
npm run dev        # syncs analysis JSONs into public/data/, starts Vite
npm run typecheck
npm run build
```

Data flow: `scripts/sync-data.mjs` bundles `../analysis/{scorecards,ledger,sellers.json}`
into `public/data/scorecards.json` (runs automatically before dev/build). In
production this JSON becomes an API response; `src/types/scorecards.ts` is the
contract.

Routes: `/` team table · `/reps/:repSlug` rep detail · `/calls/:callSlug?rep=` meeting detail.
