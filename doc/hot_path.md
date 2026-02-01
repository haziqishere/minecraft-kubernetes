# Real-Time Bus Tracker - Technical Specification

> **Principal Engineer's Perspective**: Building a real-time vehicle tracking system like Uber

## Architecture Overview

```
┌─────────────────┐      ┌──────────────┐      ┌─────────────┐
│  Spark Stream   │─────>│    Redis     │<─────│   Backend   │
│  (Kafka -> Redis)│      │  (In-Memory) │      │   (FastAPI) │
└─────────────────┘      └──────────────┘      └──────┬──────┘
                                                       │
                                                       │ WebSocket
                                                       │
                                                ┌──────▼──────┐
                                                │   Frontend  │
                                                │  (React +   │
                                                │   Leaflet)  │
                                                └─────────────┘
```

## Redis Data Model

### Key Design Pattern
**Composite Key**: `bus:{route_id}:{license_plate}`

**Why?**
- Fast O(1) lookups for specific bus
- Easy pattern scanning for route-based queries
- Natural uniqueness constraint
- Efficient memory usage

### Data Structure
```redis
# Hash per bus
HSET bus:rapid-bus-kl-1:WXY1234 
  license_plate "WXY1234"
  route_id "rapid-bus-kl-1"
  latitude "3.1390"
  longitude "101.6869"
  bearing "45.2"
  speed "35.5"
  category "bus"
  last_updated "1706745600"

# TTL: 5 minutes (auto-cleanup for inactive buses)
EXPIRE bus:rapid-bus-kl-1:WXY1234 300
```

### Indexing Strategy
```redis
# Set for quick route lookup
SADD route:rapid-bus-kl-1:buses "WXY1234" "ABC5678"

# Geospatial index (optional, for radius queries)
GEOADD buses:geo 101.6869 3.1390 "rapid-bus-kl-1:WXY1234"
```

## Real-Time Data Loading Strategy

### The "Uber Approach" - WebSocket + Optimistic Updates

**Problem**: HTTP polling every second = wasteful, laggy
**Solution**: WebSocket push + interpolation

### Three-Layer Strategy

#### 1. **WebSocket Push** (Primary)
- Backend pushes updates when Redis changes
- Client receives updates immediately
- No polling overhead
- Real-time latency: <100ms

#### 2. **Client-Side Interpolation** (Smoothness)
- Animate markers between updates
- Linear interpolation for position
- Gives "seamless movement" effect
- Updates appear every 60fps, data arrives every 2-5s

#### 3. **Fallback HTTP Polling** (Reliability)
- If WebSocket disconnects
- Poll every 3 seconds
- Graceful degradation

### Update Frequency Tuning

```python
# Backend: Intelligent throttling
# Don't push EVERY Redis update to clients

# Group updates in time windows
UPDATE_INTERVAL = 2  # seconds
SIGNIFICANT_MOVEMENT = 10  # meters

def should_push_update(old_pos, new_pos):
    """Only push if bus moved significantly"""
    distance = haversine(old_pos, new_pos)
    return distance > SIGNIFICANT_MOVEMENT
```

**Why 2 seconds?**
- Spark streaming writes to Redis every 1-2s
- Buses moving at 40km/h = ~22m per 2s = visible movement
- Balance between smoothness and network overhead
- Uber uses 3-5s intervals for driver locations

## Project Structure

```
realtime-bus-tracker/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── redis_client.py      # Redis connection
│   ├── websocket_manager.py # WebSocket handler
│   ├── models.py            # Pydantic models
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── BusMap.jsx
│   │   │   ├── BusMarker.jsx
│   │   │   └── RouteOverlay.jsx
│   │   ├── hooks/
│   │   │   └── useRealtimeBuses.js
│   │   └── utils/
│   │       └── interpolation.js
│   ├── package.json
│   └── vite.config.js
├── docker-compose.yml       # Redis deployment
└── README.md
```

## Backend Implementation

### 1. Redis Client (`redis_client.py`)

```python
import redis
import json
from typing import List, Dict, Optional

class BusRedisClient:
    def __init__(self, host='localhost', port=6379):
        self.client = redis.Redis(
            host=host, 
            port=port, 
            decode_responses=True
        )
    
    def get_all_buses(self) -> List[Dict]:
        """Fetch all active buses"""
        buses = []
        # Scan pattern: bus:*
        for key in self.client.scan_iter("bus:*", count=100):
            bus_data = self.client.hgetall(key)
            if bus_data:
                buses.append({
                    'license_plate': bus_data['license_plate'],
                    'route_id': bus_data['route_id'],
                    'latitude': float(bus_data['latitude']),
                    'longitude': float(bus_data['longitude']),
                    'bearing': float(bus_data.get('bearing', 0)),
                    'speed': float(bus_data.get('speed', 0)),
                    'category': bus_data.get('category', 'bus')
                })
        return buses
    
    def get_buses_by_route(self, route_id: str) -> List[Dict]:
        """Fetch buses for specific route"""
        buses = []
        pattern = f"bus:{route_id}:*"
        for key in self.client.scan_iter(pattern, count=100):
            bus_data = self.client.hgetall(key)
            if bus_data:
                buses.append(self._parse_bus_data(bus_data))
        return buses
    
    def subscribe_to_updates(self):
        """Subscribe to Redis keyspace notifications"""
        # Enable keyspace notifications in Redis:
        # redis-cli> CONFIG SET notify-keyspace-events Kh
        pubsub = self.client.pubsub()
        pubsub.psubscribe('__keyspace@0__:bus:*')
        return pubsub
```

### 2. WebSocket Manager (`websocket_manager.py`)

```python
from fastapi import WebSocket
from typing import Set, Dict
import asyncio
import json

class WebSocketManager:
    def __init__(self, redis_client):
        self.active_connections: Set[WebSocket] = set()
        self.redis_client = redis_client
        self._running = False
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        
        # Start Redis listener if not running
        if not self._running:
            asyncio.create_task(self._listen_redis_updates())
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        """Send update to all connected clients"""
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        
        # Cleanup disconnected clients
        self.active_connections -= disconnected
    
    async def _listen_redis_updates(self):
        """Listen to Redis updates and push to clients"""
        self._running = True
        
        while True:
            # Throttled approach: Send bulk updates every 2 seconds
            await asyncio.sleep(2)
            
            try:
                buses = self.redis_client.get_all_buses()
                await self.broadcast({
                    'type': 'bus_update',
                    'data': buses,
                    'timestamp': time.time()
                })
            except Exception as e:
                print(f"Error broadcasting: {e}")
```

### 3. FastAPI Main (`main.py`)

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from redis_client import BusRedisClient
from websocket_manager import WebSocketManager
import time

app = FastAPI(title="Real-Time Bus Tracker API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Redis and WebSocket manager
redis_client = BusRedisClient(host='localhost', port=6379)
ws_manager = WebSocketManager(redis_client)

@app.get("/api/buses")
async def get_all_buses():
    """HTTP endpoint for initial load / fallback"""
    return {
        "buses": redis_client.get_all_buses(),
        "timestamp": time.time()
    }

@app.get("/api/buses/route/{route_id}")
async def get_buses_by_route(route_id: str):
    """Get buses for specific route"""
    return {
        "buses": redis_client.get_buses_by_route(route_id),
        "route_id": route_id,
        "timestamp": time.time()
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await ws_manager.connect(websocket)
    
    try:
        # Send initial data
        initial_data = redis_client.get_all_buses()
        await websocket.send_json({
            'type': 'initial',
            'data': initial_data,
            'timestamp': time.time()
        })
        
        # Keep connection alive
        while True:
            # Client can send ping to keep alive
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

### 4. Requirements (`requirements.txt`)

```txt
fastapi==0.109.0
uvicorn[standard]==0.27.0
redis==5.0.1
websockets==12.0
python-multipart==0.0.6
```

## Frontend Implementation

### 1. WebSocket Hook (`hooks/useRealtimeBuses.js`)

```javascript
import { useState, useEffect, useRef } from 'react';

export const useRealtimeBuses = () => {
  const [buses, setBuses] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const ws = useRef(null);
  const reconnectTimeout = useRef(null);

  const connect = () => {
    ws.current = new WebSocket('ws://localhost:8000/ws');
    
    ws.current.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
    };
    
    ws.current.onmessage = (event) => {
      const message = JSON.parse(event.data);
      
      if (message.type === 'initial' || message.type === 'bus_update') {
        setBuses(message.data);
      }
    };
    
    ws.current.onclose = () => {
      console.log('WebSocket disconnected');
      setIsConnected(false);
      
      // Reconnect after 3 seconds
      reconnectTimeout.current = setTimeout(() => {
        connect();
      }, 3000);
    };
    
    ws.current.onerror = (error) => {
      console.error('WebSocket error:', error);
      ws.current.close();
    };
  };

  useEffect(() => {
    connect();
    
    // Heartbeat to keep connection alive
    const heartbeat = setInterval(() => {
      if (ws.current?.readyState === WebSocket.OPEN) {
        ws.current.send('ping');
      }
    }, 30000);
    
    return () => {
      clearInterval(heartbeat);
      clearTimeout(reconnectTimeout.current);
      ws.current?.close();
    };
  }, []);

  // Fallback: HTTP polling if WebSocket fails
  useEffect(() => {
    if (!isConnected) {
      const pollInterval = setInterval(async () => {
        try {
          const response = await fetch('http://localhost:8000/api/buses');
          const data = await response.json();
          setBuses(data.buses);
        } catch (error) {
          console.error('Polling failed:', error);
        }
      }, 3000);
      
      return () => clearInterval(pollInterval);
    }
  }, [isConnected]);

  return { buses, isConnected };
};
```

### 2. Interpolation Utility (`utils/interpolation.js`)

```javascript
/**
 * Linear interpolation between two positions
 * Creates smooth animation between WebSocket updates
 */
export const interpolatePosition = (start, end, progress) => {
  return {
    lat: start.lat + (end.lat - start.lat) * progress,
    lng: start.lng + (end.lng - start.lng) * progress,
    bearing: interpolateBearing(start.bearing, end.bearing, progress)
  };
};

/**
 * Interpolate bearing (handle 360° wrapping)
 */
const interpolateBearing = (start, end, progress) => {
  let diff = end - start;
  
  // Take shortest path around circle
  if (diff > 180) diff -= 360;
  if (diff < -180) diff += 360;
  
  return (start + diff * progress + 360) % 360;
};

/**
 * Calculate distance between two points (Haversine)
 */
export const calculateDistance = (lat1, lon1, lat2, lon2) => {
  const R = 6371e3; // Earth radius in meters
  const φ1 = lat1 * Math.PI / 180;
  const φ2 = lat2 * Math.PI / 180;
  const Δφ = (lat2 - lat1) * Math.PI / 180;
  const Δλ = (lon2 - lon1) * Math.PI / 180;

  const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
          Math.cos(φ1) * Math.cos(φ2) *
          Math.sin(Δλ/2) * Math.sin(Δλ/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

  return R * c; // Distance in meters
};
```

### 3. Animated Bus Marker (`components/BusMarker.jsx`)

```javascript
import { useEffect, useRef, useState } from 'react';
import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import { interpolatePosition } from '../utils/interpolation';

export const BusMarker = ({ bus, previousPosition }) => {
  const [currentPosition, setCurrentPosition] = useState({
    lat: bus.latitude,
    lng: bus.longitude,
    bearing: bus.bearing
  });
  
  const animationRef = useRef(null);
  const startTime = useRef(Date.now());
  const ANIMATION_DURATION = 2000; // 2 seconds to match backend interval

  useEffect(() => {
    if (!previousPosition) {
      setCurrentPosition({
        lat: bus.latitude,
        lng: bus.longitude,
        bearing: bus.bearing
      });
      return;
    }

    // Animate from previous to current position
    startTime.current = Date.now();
    
    const animate = () => {
      const elapsed = Date.now() - startTime.current;
      const progress = Math.min(elapsed / ANIMATION_DURATION, 1);
      
      const interpolated = interpolatePosition(
        previousPosition,
        { lat: bus.latitude, lng: bus.longitude, bearing: bus.bearing },
        progress
      );
      
      setCurrentPosition(interpolated);
      
      if (progress < 1) {
        animationRef.current = requestAnimationFrame(animate);
      }
    };
    
    animationRef.current = requestAnimationFrame(animate);
    
    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [bus.latitude, bus.longitude, bus.bearing, previousPosition]);

  // Custom icon with rotation
  const busIcon = L.divIcon({
    html: `
      <div style="transform: rotate(${currentPosition.bearing}deg);">
        🚌
      </div>
    `,
    className: 'bus-marker',
    iconSize: [30, 30],
    iconAnchor: [15, 15]
  });

  return (
    <Marker position={[currentPosition.lat, currentPosition.lng]} icon={busIcon}>
      <Popup>
        <strong>Route:</strong> {bus.route_id}<br/>
        <strong>Plate:</strong> {bus.license_plate}<br/>
        <strong>Speed:</strong> {bus.speed.toFixed(1)} km/h
      </Popup>
    </Marker>
  );
};
```

### 4. Main Map Component (`components/BusMap.jsx`)

```javascript
import { MapContainer, TileLayer } from 'react-leaflet';
import { useRealtimeBuses } from '../hooks/useRealtimeBuses';
import { BusMarker } from './BusMarker';
import { useState, useEffect } from 'react';
import 'leaflet/dist/leaflet.css';

export const BusMap = () => {
  const { buses, isConnected } = useRealtimeBuses();
  const [previousPositions, setPreviousPositions] = useState({});

  useEffect(() => {
    // Store previous positions for interpolation
    const newPositions = {};
    buses.forEach(bus => {
      const key = `${bus.route_id}:${bus.license_plate}`;
      newPositions[key] = {
        lat: bus.latitude,
        lng: bus.longitude,
        bearing: bus.bearing
      };
    });
    setPreviousPositions(newPositions);
  }, [buses]);

  return (
    <div style={{ position: 'relative' }}>
      {/* Connection status indicator */}
      <div style={{
        position: 'absolute',
        top: 10,
        right: 10,
        zIndex: 1000,
        background: isConnected ? '#4CAF50' : '#f44336',
        color: 'white',
        padding: '8px 16px',
        borderRadius: '4px',
        fontWeight: 'bold'
      }}>
        {isConnected ? '🟢 Live' : '🔴 Reconnecting...'}
      </div>

      <MapContainer 
        center={[3.1390, 101.6869]} 
        zoom={13} 
        style={{ height: '100vh', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        
        {buses.map(bus => {
          const key = `${bus.route_id}:${bus.license_plate}`;
          return (
            <BusMarker
              key={key}
              bus={bus}
              previousPosition={previousPositions[key]}
            />
          );
        })}
      </MapContainer>
    </div>
  );
};
```

### 5. App Entry (`App.jsx`)

```javascript
import { BusMap } from './components/BusMap';

function App() {
  return (
    <div className="App">
      <BusMap />
    </div>
  );
}

export default App;
```

### 6. Package.json

```json
{
  "name": "realtime-bus-tracker",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-leaflet": "^4.2.1",
    "leaflet": "^1.9.4"
  },
  "devDependencies": {
    "@types/react": "^18.2.43",
    "@types/react-dom": "^18.2.17",
    "@vitejs/plugin-react": "^4.2.1",
    "vite": "^5.0.8"
  }
}
```

## Deployment

### Docker Compose (`docker-compose.yml`)

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    container_name: bus-tracker-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes --notify-keyspace-events Kh
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3

volumes:
  redis-data:
```

## Running the Application

### 1. Start Redis
```bash
docker-compose up -d
```

### 2. Start Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Start Frontend
```bash
cd frontend
npm install
npm run dev
```

Access: `http://localhost:5173`

## Performance Considerations

### Redis Optimization
```bash
# Redis config tuning
maxmemory 512mb
maxmemory-policy allkeys-lru  # Evict least recently used

# Enable keyspace notifications (for pub/sub)
notify-keyspace-events Kh
```

### Backend Scaling
- Use Redis connection pooling
- Implement rate limiting per client
- Add Redis replica for read scaling if needed

### Frontend Optimization
- Virtualize markers if >1000 buses (react-window)
- Debounce map interactions
- Lazy load routes (only visible area)

## Monitoring

### Key Metrics
```python
# In production, track:
- WebSocket connections: Active count
- Redis operations: GET/SET latency
- Update frequency: Messages/second
- Client-side: FPS, animation smoothness
```

## Best Practices Summary

### ✅ DO
- Use WebSocket for push updates
- Interpolate between positions for smoothness
- Implement fallback HTTP polling
- Use composite Redis keys for fast lookups
- Add TTL to prevent stale data
- Throttle updates (2-5s intervals)
- Implement reconnection logic

### ❌ DON'T
- Poll every 100ms (wasteful)
- Send every Redis update to clients (throttle!)
- Store historical data in Redis (use TimescaleDB)
- Update map on every pixel change
- Forget error handling
- Skip connection status UI

## Future Enhancements

1. **Route Overlays**: Fetch static route paths from PostGIS
2. **Clustering**: Group nearby buses on zoom out
3. **Playback**: Store snapshots for replay
4. **Alerts**: Push notifications for delays
5. **Analytics**: Track average speeds, delays

---

**TL;DR**: WebSocket push + client-side interpolation = Uber-like smoothness with minimal backend overhead. Update every 2s, animate at 60fps.