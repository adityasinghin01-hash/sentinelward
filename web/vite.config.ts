import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],server:{proxy:{'/api':{target:'http://127.0.0.1:8000',changeOrigin:false},'/ws':{target:'ws://127.0.0.1:8000',ws:true,changeOrigin:false}}},test:{environment:'jsdom',include:['src/**/*.test.{ts,tsx}'],setupFiles:['./src/test-setup.ts']}});
