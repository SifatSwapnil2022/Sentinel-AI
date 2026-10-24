# The dashboard, built to read a live API on the same origin and served by nginx, which
# proxies /v1/ to the API container.

FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
ARG VITE_SENTINEL_API=/
ENV VITE_SENTINEL_API=${VITE_SENTINEL_API}
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
