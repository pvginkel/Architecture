# ---- build stage ----
FROM node:22-alpine AS build
WORKDIR /app

COPY viewer/package*.json ./
RUN npm install

COPY viewer/ ./
RUN npm run build

# ---- runtime stage ----
FROM nginx:alpine
COPY viewer/nginx.conf /etc/nginx/conf.d/default.conf
# Built assets are served from /viewer/ (vite.config.ts base).
COPY --from=build /app/dist /usr/share/nginx/html/viewer
EXPOSE 80
