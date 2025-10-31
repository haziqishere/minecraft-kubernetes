cd ~/Projects/server/minecraft-kubernetes

cat > Makefile <<'EOF'
.PHONY: help build-minecraft run-minecraft deploy-local sync-argocd backup logs clean

.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

build-minecraft: ## Build Minecraft Docker image locally
	@echo "Building Minecraft image..."
	docker build -t minecraft-custom:local docker/minecraft/
	@echo "✓ Image built: minecraft-custom:local"

run-minecraft: ## Run Minecraft locally (port 25565)
	@echo "Starting Minecraft server..."
	docker run -d -p 25565:25565 --name minecraft-local minecraft-custom:local
	@echo "✓ Server running at localhost:25565"
	@echo "  Stop with: docker stop minecraft-local"

stop-minecraft: ## Stop local Minecraft container
	docker stop minecraft-local 2>/dev/null || true
	docker rm minecraft-local 2>/dev/null || true
	@echo "✓ Minecraft stopped"

deploy-local: ## Deploy Minecraft to local K3s cluster
	@echo "Deploying to K3s..."
	kubectl apply -f kubernetes/minecraft/
	@echo "✓ Deployed to minecraft namespace"

sync-argocd: ## Manually sync ArgoCD application
	@echo "Syncing ArgoCD..."
	argocd app sync minecraft-stack --grpc-web
	@echo "✓ ArgoCD synced"

logs: ## Show Minecraft pod logs
	kubectl logs -n minecraft -l app=minecraft --tail=100 -f

backup: ## Backup Minecraft world
	@echo "Backing up world..."
	kubectl exec -n minecraft deployment/minecraft-server -- rcon-cli save-all
	@echo "✓ World saved"

status: ## Show status of all services
	@echo "=== Minecraft ==="
	kubectl get pods -n minecraft
	@echo ""
	@echo "=== ArgoCD ==="
	kubectl get pods -n argocd
	@echo ""
	@echo "=== Observability ==="
	kubectl get pods -n observability

test-build: ## Test build without pushing
	@echo "Testing Docker build..."
	docker build --no-cache -t minecraft-custom:test docker/minecraft/
	@echo "✓ Build successful"

clean: ## Clean up local Docker images
	@echo "Cleaning up..."
	docker rmi minecraft-custom:local 2>/dev/null || true
	docker rmi minecraft-custom:test 2>/dev/null || true
	@echo "✓ Cleaned"

urls: ## Show all service URLs
	@echo "🎮 Services:"
	@echo "  Minecraft:        kroni-smp.taile695bc.ts.net:30565"
	@echo "  Traefik:          http://kroni-smp.taile695bc.ts.net:30888/dashboard/"
	@echo "  ArgoCD:           http://kroni-smp.taile695bc.ts.net:30081"
	@echo "  Grafana:          http://kroni-smp.taile695bc.ts.net:30083"
	@echo "  Prefect:          http://kroni-smp.taile695bc.ts.net:30082"
EOF

chmod +x Makefile