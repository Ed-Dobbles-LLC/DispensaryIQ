FROM caddy:2.8-alpine

# python3 + tzdata for the Curaleaf daily-edition renderer (brief #5799)
RUN apk add --no-cache python3 tzdata

# Copy the static site
COPY site/ /srv/

# Copy Caddy config
COPY Caddyfile /etc/caddy/Caddyfile

# Curaleaf First Page: daily edition, published by 09:00 CT (#5807), rendered in place into /srv/curaleaf/
COPY scripts/curaleaf_scorecard.py /app/curaleaf_scorecard.py
COPY deploy/curaleaf-publish.sh deploy/entrypoint.sh /app/
COPY deploy/crontab /etc/crontabs/root
RUN chmod +x /app/curaleaf-publish.sh /app/entrypoint.sh

# Caddy reads $PORT from Railway at runtime
EXPOSE 8080

# crond + boot render, then Caddy as PID 1 (same command as the base image CMD)
CMD ["/app/entrypoint.sh"]
