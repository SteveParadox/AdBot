"""Admin-only, redacted per-process egress status; no endpoint addresses or credentials."""
import json
from fastapi import APIRouter, Request, HTTPException
from .content import Admin
from .outbound import manager

router = APIRouter(prefix='/api/admin/network')


@router.get('')
async def diagnostics(request: Request, admin: Admin):
    snapshots = [manager().snapshot()]
    redis = getattr(request.app.state, 'redis', None)
    if redis:
        try:
            async for key in redis.scan_iter(match='adbot:egress:instance:*', count=100):
                value = await redis.get(key)
                if value:
                    snapshot = json.loads(value)
                    if snapshot['instance'] != snapshots[0]['instance']:
                        snapshots.append(snapshot)
                if len(snapshots) >= 100:
                    break
        except Exception:
            raise HTTPException(503, 'Network monitoring temporarily unavailable') from None
    return {'instances': snapshots, 'scope': 'shared-heartbeats' if redis else 'this-process-only'}
