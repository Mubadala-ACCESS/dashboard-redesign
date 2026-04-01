from fastapi import FastAPI
from routers import map, stations, live

app = FastAPI(title="ACCESS Dashboard API", version="0.1.0")

app.include_router(map.router, prefix="/api/map", tags=["map"])
app.include_router(stations.router, prefix="/api/stations", tags=["stations"])
app.include_router(live.router, prefix="/api/stations", tags=["live"])

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
