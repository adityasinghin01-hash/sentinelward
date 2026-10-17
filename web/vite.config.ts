import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
declare const process: {env: Record<string, string | undefined>};
const api = process.env.SW_API_TARGET || 'http://127.0.0.1:8000';
export default defineConfig({plugins:[react()],server:{proxy:{'/api':{target:api,changeOrigin:false},'/ws':{target:api.replace(/^http/,'ws'),ws:true,changeOrigin:false}}},test:{environment:'jsdom',include:['src/**/*.test.{ts,tsx}'],setupFiles:['./src/test-setup.ts']}});
