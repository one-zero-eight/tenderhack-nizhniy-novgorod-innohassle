FROM node:20-alpine AS build

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN corepack enable pnpm && corepack prepare pnpm@10.22.0 --activate
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm run build

# Nginx
FROM nginx:stable-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000
CMD [ "nginx", "-g", "daemon off;" ]
