# =============================================================================
# Interface web PrediCare : build Vite puis service par nginx
# =============================================================================

# ---------- Etape 1 : construction du bundle ------------------------------
FROM node:22-alpine AS builder

ARG VITE_API_BASE_URL=""
ARG VITE_API_GATEWAY_URL=/api

WORKDIR /app

# Les manifestes d'abord : la couche d'install dependances est reutilisee
# tant que les manifestes ne changent pas. Le verrou est copie avec, sans
# quoi `npm ci` refuse de s'executer.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY apps/web/ ./

# Vite inlege ses variables au moment du build : `VITE_API_GATEWAY_URL` est
# le chemin appele par le navigateur, `VITE_API_BASE_URL` est vide en
# production puisque tout est servi sur la meme origine par la passerelle.
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_API_GATEWAY_URL=${VITE_API_GATEWAY_URL}

RUN npm run build

# ---------- Etape 2 : service statique ------------------------------------
FROM nginx:1.27-alpine AS runtime

# Configuration dediee : on ecrase celle de l'image officielle, qui ecoute
# sur le port 80 et sert un index par defaut.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY apps/web/nginx.conf /etc/nginx/conf.d/predicare.conf
COPY --from=builder /app/dist /usr/share/nginx/html

# Conteneur sans privileges : nginx écoute sur 8080, port non reserve.
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1