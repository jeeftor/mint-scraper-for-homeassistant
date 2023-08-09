# Local Development directions

```bash

docker build -f Dockerfile.dev -t appdaemon .

mkdir -p /tmp/compiled /tmp/dashboards /tmp/namespaces /tmp/www

docker run --rm --name appdaemon --entrypoint=ash \
--env-file .env \
-p 5050:5050 \
-v "$(pwd)/apps/mint-scraper-for-homeassistant:/conf/apps/mint_scraper_app" \
-v /tmp/compiled:/conf/apps/compiled \
-v /tmp/dashboards:/conf/apps/dashboards \
-v /tmp/namespaces:/conf/apps/namespaces \
-v /tmp/www:/conf/apps/www \
-v "$(pwd)/.dev/conf:/conf" \
   -it appdaemon

```
