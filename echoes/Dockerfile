# Stage 1: build Echoes Inspector (React + Vite)
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vector-rs base URL is baked at build time. Pass via:
#   docker build --build-arg VITE_VECTOR_API_URL=https://... .
ARG VITE_VECTOR_API_URL
ENV VITE_VECTOR_API_URL=$VITE_VECTOR_API_URL
RUN npm run build

# Stage 2: nginx static serve
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html

RUN printf 'server {\n\
    listen 8080;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    add_header X-Content-Type-Options "nosniff" always;\n\
    add_header X-Frame-Options "DENY" always;\n\
    add_header X-XSS-Protection "1; mode=block" always;\n\
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;\n\
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;\n\
    # Hashed Vite assets (/assets/index-XXX.js etc.) — safe to cache forever.\n\
    location /assets/ {\n\
        add_header Cache-Control "public, max-age=31536000, immutable" always;\n\
        try_files $uri =404;\n\
    }\n\
    # index.html must always revalidate so new deploys point at fresh asset hashes.\n\
    location = /index.html {\n\
        add_header Cache-Control "no-cache" always;\n\
        try_files $uri =404;\n\
    }\n\
    location / {\n\
        add_header Cache-Control "no-cache" always;\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
