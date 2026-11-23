# The web image: the built PWA behind nginx, as an unprivileged user on :8080.
FROM node:24-alpine AS build

# pnpm comes from "packageManager" in package.json.
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build


FROM nginxinc/nginx-unprivileged:1.31-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
