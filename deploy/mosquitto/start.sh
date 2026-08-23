#!/bin/sh
set -eu

: "${MQTT_LEFT_PASSWORD:?MQTT_LEFT_PASSWORD is required}"
: "${MQTT_RIGHT_PASSWORD:?MQTT_RIGHT_PASSWORD is required}"
: "${MQTT_BACKEND_PASSWORD:?MQTT_BACKEND_PASSWORD is required}"

password_file=/mosquitto/data/passwords
umask 077
mosquitto_passwd -b -c "$password_file" rail-left-01 "$MQTT_LEFT_PASSWORD"
mosquitto_passwd -b "$password_file" rail-right-01 "$MQTT_RIGHT_PASSWORD"
mosquitto_passwd -b "$password_file" railtwin-backend "$MQTT_BACKEND_PASSWORD"

mqtt_tls=$(printf '%s' "${MQTT_TLS:-true}" | tr '[:upper:]' '[:lower:]')
if [ "$mqtt_tls" = "true" ] || [ "$mqtt_tls" = "1" ] || [ "$mqtt_tls" = "yes" ] || [ "$mqtt_tls" = "on" ]; then
  certfile="${MQTT_CERTFILE:-/etc/letsencrypt/live/${SSL_DOMAIN:?SSL_DOMAIN is required for MQTT TLS}/fullchain.pem}"
  keyfile="${MQTT_KEYFILE:-/etc/letsencrypt/live/${SSL_DOMAIN:?SSL_DOMAIN is required for MQTT TLS}/privkey.pem}"
  for certificate in "$certfile" "$keyfile"; do
    if [ ! -s "$certificate" ]; then
      echo "[mosquitto] missing TLS file: $certificate" >&2
      exit 1
    fi
  done
  exec mosquitto -c /mosquitto/config/mosquitto.conf
fi

exec mosquitto -c /mosquitto/config/mosquitto.local.conf
