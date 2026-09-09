FROM node:20-alpine AS build
WORKDIR /app
ARG VITE_ENABLE_PORTFOLIO_DEMO=true
ENV VITE_ENABLE_PORTFOLIO_DEMO=$VITE_ENABLE_PORTFOLIO_DEMO
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
ENV NGINX_RESOLVER=127.0.0.11
ENV SIMULATOR_UPSTREAM=http://render-simulator:8080
ENV AGENT_UPSTREAM=http://production-director-agent:8090
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
