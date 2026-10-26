import { defineConfig, Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

const isSingleFile = process.env.SINGLE_FILE === '1';

const apkMimePlugin = (): Plugin => ({
  name: 'apk-mime-headers',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (req.url && req.url.split('?')[0].endsWith('.apk')) {
        res.setHeader('Content-Type', 'application/vnd.android.package-archive');
        res.setHeader('Content-Disposition', 'attachment; filename="K-Craft-Korea.apk"');
      }
      next();
    });
  },
});

export default defineConfig({
  base: './',
  plugins: isSingleFile ? [react(), viteSingleFile()] : [react(), apkMimePlugin()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
    cors: true,
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    allowedHosts: true,
  },
});
