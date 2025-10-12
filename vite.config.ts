import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ command }) => {
	const isDev = command === 'serve'
	return {
		// serve at '/' during dev for convenience; when building for production
		// emit asset paths under '/ui/' so the Python service can mount dist at
		// /ui and assets are referenced correctly
		base: isDev ? '/' : '/ui/',
		root: path.resolve(__dirname, 'src', 'kitchen-ui'),
		plugins: [react()],
		build: {
			outDir: path.resolve(__dirname, 'dist', 'kitchen-ui'),
			emptyOutDir: true,
		},
		server: {
			port: 5173,
			proxy: {
				'/nodes': {
					target: 'http://localhost:8000',
					changeOrigin: true,
					secure: false,
				},
				'/health': {
					target: 'http://localhost:8000',
					changeOrigin: true,
					secure: false,
				},
				'/stats': {
					target: 'http://localhost:8000',
					changeOrigin: true,
					secure: false,
				},
			},
		},
	}
})

