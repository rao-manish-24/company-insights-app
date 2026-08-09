.PHONY: up down logs logs-backend rebuild health demo

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

logs-file:
	@mkdir -p logs
	@touch logs/companyinsights.log
	tail -f logs/companyinsights.log

rebuild:
	docker compose up --build -d --force-recreate

health:
	curl -s http://localhost:8000/api/health | python3 -m json.tool

demo:
	@EMAIL="demo+$$(date +%s)@example.com"; \
	PASS="demopass123"; \
	TOKEN=$$(curl -s -X POST http://localhost:8000/api/auth/register \
	  -H 'Content-Type: application/json' \
	  -d "{\"email\":\"$$EMAIL\",\"password\":\"$$PASS\",\"display_name\":\"Demo\"}" \
	  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])'); \
	curl -s -X POST http://localhost:8000/api/analyze \
	  -H 'Content-Type: application/json' \
	  -H "Authorization: Bearer $$TOKEN" \
	  -d '{"company_name":"Microsoft"}' | python3 -m json.tool
