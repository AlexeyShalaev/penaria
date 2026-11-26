# The web image: the built PWA behind nginx, as an unprivileged user on :8080.
FROM node:24-alpine AS build

# pnpm comes from "packageManager" in package.json.
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build


FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime

# Where /api goes; the name of the server's service in the Compose file and the Helm chart.
# The entrypoint fills NGINX_LOCAL_RESOLVERS from the container's own DNS settings.
ENV PENARIA_API_UPSTREAM=http://penaria-server:8000 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 trusted-proxies.sh /docker-entrypoint.d/30-penaria-trusted-proxies.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
