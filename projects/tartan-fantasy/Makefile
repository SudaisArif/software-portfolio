.PHONY: dev sync history live prices check check-cloudflare build cloudflare-dev

dev:
	python3 scripts/dev_server.py

sync:
	python3 scripts/sync_cmu_data.py
	python3 scripts/sync_cmu_history.py
	python3 scripts/sync_ncaa_data.py

history:
	python3 scripts/sync_cmu_history.py

live:
	python3 scripts/sync_ncaa_data.py --watch

prices:
	python3 scripts/price_players.py

check:
	python3 scripts/check_data.py
	python3 scripts/check_leagues.py
	npm run check
	npm run check:bank-api
	npm run check:auth

build:
	npm run build

cloudflare-dev:
	npm run dev:cloudflare

check-cloudflare:
	python3 scripts/check_cloudflare.py
