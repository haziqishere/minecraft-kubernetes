# Minecraft K3s Server

Minecraft server running on K3s with Tailscale VPN, managed via ArgoCD.

## Components
- Minecraft Server (Paper)
- ArgoCD (GitOps)
- Prefect (Orchestration)
- Grafana Stack (Monitoring)
- Traefik (Ingress)

## Access
- Minecraft: `kroni-smp.taile695bc.ts.net:30565`
- Traefik: `http://kroni-smp.taile695bc.ts.net:30888/dashboard/`
- ArgoCD: `http://kroni-smp.taile695bc.ts.net:30081`
- Grafana: `http://http://kroni-smp.taile695bc.ts.net:30083/`
- Prefect: `http://kroni-smp.taile695bc.ts.net:30082`