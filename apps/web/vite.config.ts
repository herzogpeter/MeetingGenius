import fs from 'node:fs'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const httpsCertFile = process.env.MG_DEV_HTTPS_CERT
const httpsKeyFile = process.env.MG_DEV_HTTPS_KEY

if ((httpsCertFile && !httpsKeyFile) || (!httpsCertFile && httpsKeyFile)) {
  throw new Error('Set both MG_DEV_HTTPS_CERT and MG_DEV_HTTPS_KEY (or neither).')
}

const httpsConfig =
  httpsCertFile && httpsKeyFile
    ? {
        cert: fs.readFileSync(path.resolve(httpsCertFile)),
        key: fs.readFileSync(path.resolve(httpsKeyFile)),
      }
    : undefined

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  ...(httpsConfig ? { server: { https: httpsConfig } } : {}),
})
