# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import AnyHttpUrl, BaseModel

from app.services.playback import handle_tv, handle_video

router = APIRouter()


class ResolveIn(BaseModel):
    url: AnyHttpUrl
    headers: Optional[Dict[str, str]] = None
    useProxy: Optional[bool] = False


@router.api_route("/tv", methods=["GET", "HEAD"])
def tv_get(request: Request, u: AnyHttpUrl = Query(...), useProxy: bool = Query(False)):
    data = handle_tv(request, str(u), None, useProxy)
    if not data.get("ok") or not data.get("resolvedUrl"):
        raise HTTPException(status_code=502, detail="unable_to_resolve")
    return RedirectResponse(url=data["resolvedUrl"], status_code=302)


@router.api_route("/video", methods=["GET", "HEAD"])
def video_get(request: Request, u: AnyHttpUrl = Query(...), useProxy: bool = Query(False)):
    data = handle_video(request, str(u), None, useProxy)
    if not data.get("ok") or not data.get("resolvedUrl"):
        raise HTTPException(status_code=502, detail="unable_to_resolve")
    return RedirectResponse(url=data["resolvedUrl"], status_code=302)


@router.api_route("/play", methods=["GET", "HEAD"])  # alias per /tv
def play_get(request: Request, u: AnyHttpUrl = Query(...), useProxy: bool = Query(False)):
    data = handle_tv(request, str(u), None, useProxy)
    if not data.get("ok") or not data.get("resolvedUrl"):
        raise HTTPException(status_code=502, detail="unable_to_resolve")
    return RedirectResponse(url=data["resolvedUrl"], status_code=302)


@router.get("/debug/tv")
def tv_debug(request: Request, u: AnyHttpUrl = Query(...), useProxy: bool = Query(False)):
    try:
        data = handle_tv(request, str(u), None, useProxy)
        return JSONResponse(data)
    except HTTPException as e:
        return JSONResponse({"detail": f"debug_tv_error: {e.detail}"}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"detail": f"debug_tv_error: {e}"}, status_code=500)


@router.get("/debug/video")
def video_debug(request: Request, u: AnyHttpUrl = Query(...), useProxy: bool = Query(False)):
    try:
        data = handle_video(request, str(u), None, useProxy)
        return JSONResponse(data)
    except HTTPException as e:
        return JSONResponse({"detail": f"debug_video_error: {e.detail}"}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"detail": f"debug_video_error: {e}"}, status_code=500)


@router.post("/tv")
def tv_post(request: Request, payload: ResolveIn = Body(...)):
    return JSONResponse(handle_tv(request, str(payload.url), payload.headers, payload.useProxy or False))


@router.post("/video")
def video_post(request: Request, payload: ResolveIn = Body(...)):
    return JSONResponse(handle_video(request, str(payload.url), payload.headers, payload.useProxy or False))
