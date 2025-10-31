# Minecraft K3s Infrastructure

Production-ready Minecraft server running on K3s with full GitOps automation, monitoring, and CI/CD pipelines.

## 🏗️ Architecture
```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   GitHub    │────▶│ GitHub Actions│────▶│ Docker Hub  │
│ (Source)    │     │   (Build CI)  │     │ (Registry)  │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                  │
                                                  ▼
                    ┌──────────────┐     ┌─────────────┐
                    │   ArgoCD     │────▶│  K3s Cluster│
                    │  (Deploy CD) │     │             │
                    └──────────────┘     └─────────────┘
```

## 📦 Components

- **Minecraft Server** - Paper server with custom mods
- **ArgoCD** - GitOps continuous deployment
- **Prefect** - Workflow orchestration
- **Grafana Stack** - Monitoring and observability
- **Traefik** - Ingress controller and load balancer
- **OpenTelemetry** - Metrics collection
- **Tailscale** - Secure VPN access

## 🚀 Quick Start

### Prerequisites
- K3s cluster running
- Docker installed
- kubectl configured
- GitHub account with repo access

### Deploy Infrastructure
```bash
# Clone repository
git clone https://github.com/haziqishere/minecraft-kubernetes
cd minecraft-kubernetes

# Build Minecraft image locally (optional)
make build-minecraft

# Deploy to K3s
make deploy-local

# Check status
make status

# View all URLs
make urls
```

## 🌐 Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| Minecraft | `kroni-smp.taile695bc.ts.net:30565` | Game server |
| Traefik Dashboard | `http://kroni-smp.taile695bc.ts.net:30888/dashboard/` | Traffic routing |
| ArgoCD | `http://kroni-smp.taile695bc.ts.net:30081` | GitOps deployments |
| Grafana | `http://kroni-smp.taile695bc.ts.net:30083` | Metrics dashboards |
| Prefect | `http://kroni-smp.taile695bc.ts.net:30082` | Workflow management |

## 🔧 Development

### Adding Mods

1. Download mod JAR files
2. Place in `docker/minecraft/mods/`
3. Commit and push
4. GitHub Actions automatically builds and deploys
```bash
# Example
cd docker/minecraft/mods
wget https://example.com/mod.jar
git add mod.jar
git commit -m "feat: add new mod"
git push
```

### Local Testing
```bash
# Build image
make build-minecraft

# Run locally
make run-minecraft

# Connect to localhost:25565
```

## 📁 Repository Structure
```
minecraft-kubernetes/
├── docker/                   # Container images
│   └── minecraft/           # Minecraft server image
│       ├── Dockerfile
│       ├── mods/           # Minecraft mods
│       └── plugins/        # Minecraft plugins
├── kubernetes/              # Kubernetes manifests
│   ├── argocd/            # ArgoCD apps
│   ├── minecraft/         # Minecraft deployment
│   ├── traefik/          # Ingress controller
│   ├── prefect/          # Workflow engine
│   └── observability/    # Monitoring stack
├── .github/
│   └── workflows/         # CI/CD pipelines
├── scripts/              # Utility scripts
├── docs/                # Documentation
└── Makefile            # Common commands
```

## 🛠️ Makefile Commands
```bash
make help              # Show all available commands
make build-minecraft   # Build Docker image locally
make run-minecraft     # Run Minecraft container locally
make deploy-local      # Deploy to K3s cluster
make sync-argocd       # Manually sync ArgoCD
make logs              # Show Minecraft logs
make backup            # Backup Minecraft world
make status            # Show all pod statuses
make urls              # Display all service URLs
make clean             # Clean up local images
```

## 📚 Documentation

- [Architecture Overview](docs/architecture.md)
- [Deployment Guide](docs/deployment.md)
- [Troubleshooting](docs/troubleshooting.md)

## 🔐 Security

- Private repo access via SSH/PAT
- Secrets managed via Kubernetes secrets
- Tailscale VPN for secure access
- RCON password configured

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'feat: add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## 📝 License

This project is licensed under the MIT License.

## 👤 Author

**haziqishere**

- GitHub: [@haziqishere](https://github.com/haziqishere)

---

Built with ❤️ using Kubernetes, ArgoCD, and modern DevOps practices.