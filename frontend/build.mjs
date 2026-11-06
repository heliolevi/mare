// Gera static/dist/main.js (um arquivo só, ESM) a partir de frontend/src. Use --watch no dev.
import { build, context } from 'esbuild';

const watch = process.argv.includes('--watch');
const opcoes = {
  entryPoints: ['frontend/src/main.ts'],
  outdir: 'static/dist',
  bundle: true,
  format: 'esm',
  target: 'es2022',
  sourcemap: watch, // o mapa expõe o código-fonte original; só é gerado em desenvolvimento (npm run dev)
  minify: !watch,
  logLevel: 'info',
};

if (watch) {
  const ctx = await context(opcoes);
  await ctx.watch();
  console.log('Observando frontend/src... (Ctrl+C para sair)');
} else {
  await build(opcoes);
}
