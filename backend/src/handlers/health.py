"""GET /api/health"""
from linkpulse import http


@http.api_handler
def lambda_handler(event, context):
    return http.response(200, {"status": "ok"}, {"Cache-Control": "no-store"})
