from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings, validate_runtime_security
from .version import APP_VERSION
from .routes.health import router as health_router
from .routes.business_rules import router as rules_router
from .routes.imports import router as imports_router
from .routes.dashboard import router as dashboard_router
from .routes.analysis import router as analysis_router
from .routes.presets import router as presets_router
from .routes.tasks import router as tasks_router
from .routes.auth import router as auth_router
from .routes.admin import router as admin_router
from .routes.setup import router as setup_router
from .routes.exports import router as exports_router

validate_runtime_security()
app = FastAPI(title="百嘉瑞 BI", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(rules_router, prefix="/api")
app.include_router(imports_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(presets_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(setup_router, prefix="/api")
app.include_router(exports_router, prefix="/api")

@app.get('/api')
def root():
    return {"name": "百嘉瑞 BI", "version": APP_VERSION, "external_wdt_api": False}
