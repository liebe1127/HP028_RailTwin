#!/bin/sh
set -eu

upstream="${API_UPSTREAM:-host.docker.internal:8001}"

if [ -f /certs/fullchain.pem ] && [ -f /certs/privkey.pem ]; then
  src=/opt/railtwin/nginx.https.conf
else
  src=/opt/railtwin/nginx.http.conf
fi

sed "s#__API_UPSTREAM__#${upstream}#g" "$src" > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
