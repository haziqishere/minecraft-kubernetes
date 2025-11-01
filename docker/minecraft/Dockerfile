FROM itzg/minecraft-server:latest

# Copy mods and plugins directories (will be empty initially)
# To add mods: place .jar files in docker/minecraft/mods/
# To add plugins: place .jar files in docker/minecraft/plugins/
COPY --chown=1000:1000 mods/ /data/mods/
COPY --chown=1000:1000 plugins/ /data/plugins/

# Custom environment variables
ENV DIFFICULTY=hard \
    SPAWN_PROTECTION=0 \
    GENERATE_STRUCTURES=true \
    MAX_BUILD_HEIGHT=320 \
    VIEW_DISTANCE=10 \
    ONLINE_MODE=false

# Metadata
LABEL maintainer="haziqishere" \
      version="1.0" \
      description="Custom Minecraft server with mods and optimizations"

EXPOSE 25565 25575

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD mc-health || exit 1