# Synapse web UI: the React build served by nginx, which also proxies /api to a node.

FROM docker.io/library/node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM docker.io/library/nginx:alpine
LABEL org.opencontainers.image.title="synapse-frontend" \
      org.opencontainers.image.description="Synapse web interface"
# Which node this UI talks to, and use the container's DNS so restarts of the node are picked up.
ENV SYNAPSE_API_UPSTREAM=node-a:8000 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
