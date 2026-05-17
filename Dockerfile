FROM caddy:2.8-alpine

# Copy the static site
COPY site/ /srv/

# Copy Caddy config
COPY Caddyfile /etc/caddy/Caddyfile

# Caddy reads $PORT from Railway at runtime
EXPOSE 8080

# Caddy runs as default CMD from base image
