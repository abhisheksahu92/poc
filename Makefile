
---

# 📄 `Makefile`

```makefile
# Variables
COMPOSE = docker compose

# Build images
build:
	$(COMPOSE) build --no-cache

# Run converter
run:
	$(COMPOSE) up

# Run tests
test:
	$(COMPOSE) -f docker-compose.test.yml run --rm tests

# Clean up containers, images, and volumes
clean:
	$(COMPOSE) down --volumes --remove-orphans
	docker system prune -f
