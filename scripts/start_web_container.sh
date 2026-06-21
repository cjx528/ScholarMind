#!/bin/sh
set -eu

: "${PORT:=8080}"

mkdir -p /app/data/papers /app/logs /run/nginx

envsubst '${PORT}' \
    < /app/infra/nginx.web.conf.template \
    > /etc/nginx/conf.d/default.conf

exec supervisord -c /app/infra/supervisord.web.conf
