# frontend — local development image (Vite dev server).
# Build context is the repository ROOT (docker compose sets context: ".").
# node_modules are installed at build time and docker compose's anonymous
# /app/node_modules volume is seeded from them; the source itself is
# bind-mounted from the host so the dev server hot-reloads.
FROM node:22-alpine

ENV NODE_ENV=development

WORKDIR /app

COPY apps/frontend/package.json apps/frontend/package-lock.json ./
RUN npm ci

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]