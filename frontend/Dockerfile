FROM nginx:alpine

# Copy static files
COPY . /usr/share/nginx/html/

# Nginx config for SPA routing with security headers
RUN printf 'server {\n\
    listen 8080;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    add_header X-Content-Type-Options "nosniff" always;\n\
    add_header X-Frame-Options "DENY" always;\n\
    add_header X-XSS-Protection "1; mode=block" always;\n\
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;\n\
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
