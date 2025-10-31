# Custom Minecraft Server Image

Custom Minecraft server based on `itzg/minecraft-server` with additional mods and configurations.

## Features
- Difficulty: Hard
- Villages enabled
- Custom view distance: 10
- Health checks enabled

## Adding Mods
1. Download mod JAR files
2. Place in `mods/` directory
3. Commit and push
4. GitHub Actions will rebuild automatically

## Adding Plugins
1. Download plugin JAR files
2. Place in `plugins/` directory
3. Commit and push

## Building Locally
```bash
cd docker/minecraft
docker build -t minecraft-custom:local .
docker run -p 25565:25565 minecraft-custom:local
```

Or use the Makefile from root:
```bash
make build-minecraft
make run-minecraft
```

## Environment Variables
See [itzg/minecraft-server docs](https://github.com/itzg/docker-minecraft-server) for all available options.