FROM node:18-slim AS build
WORKDIR /app
ARG VITE_API_BASE="http://localhost:30081"
ENV VITE_API_BASE=${VITE_API_BASE}
COPY frontend/pnpm-lock.yaml frontend/package.json ./ 
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/vite.config.js frontend/eslint.config.js ./ 
COPY frontend/index.html ./ 
COPY frontend/src ./src
RUN pnpm run build

FROM nginx:1.25-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/scripts/nginx-frontend.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
