from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.admin import router as admin_router
from app.routers.joint import router as joint_router
from app.routers.sessions import router as sessions_router

settings = get_settings()

app = FastAPI(title="Mediator API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(sessions_router)
app.include_router(joint_router)
app.include_router(admin_router)


@app.get("/health")
def health():
    return {"ok": True}
