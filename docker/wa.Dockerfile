# WhatsApp Baileys VoIP + pure-TS WebRTC bridge (apps/wa)
FROM node:22-bookworm-slim

WORKDIR /app/apps/wa
COPY apps/wa/package.json apps/wa/package-lock.json ./
COPY apps/wa/scripts ./scripts
RUN npm ci

COPY apps/wa/tsconfig.json ./
COPY apps/wa/src ./src
RUN npm run build

EXPOSE 3001
CMD ["node", "dist/index.js"]
