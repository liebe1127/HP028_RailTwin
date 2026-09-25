FROM nginx:1.27-alpine

RUN apk add --no-cache curl

COPY nginx.http.conf nginx.https.conf /opt/railtwin/
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
