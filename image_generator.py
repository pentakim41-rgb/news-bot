# -*- coding: utf-8 -*-
"""
image_generator.py
--------------------
image_prompts 폴더에 저장된 프롬프트를 읽어, 선택된 이미지 생성 AI
(Hugging Face / ChatGPT GPT Image / Kling / HeyGen / Pollinations / Gemini)를
호출해 썸네일 이미지를 생성하고 images 폴더에 저장한다.

선택한 모델 한도 소진·실패 시 다른 모델로 자동 전환하지 않고,
제목 텍스트 썸네일(thumbnail_maker)로 대체한다.
"""

import os
import re
import time
import json
import hmac
import hashlib
import base64
import urllib.parse
import requests
import sys

from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError
from PIL import Image

import thumbnail_maker

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, "data", "images")

# API URLs
OPENAI_IMAGE_API_URL = "https://api.openai.com/v1/images/generations"
GEMINI_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
POLLINATIONS_GEN_URL = "https://gen.pollinations.ai/image/{prompt}"
POLLINATIONS_GEN_OPENAI_URL = "https://gen.pollinations.ai/v1/images/generations"
POLLINATIONS_LEGACY_URL = "https://image.pollinations.ai/prompt/{prompt}"
KLING_IMAGE_API_URL = "https://api.klingai.com/v1/images/generations"
HEYGEN_AVATARS_URL = "https://api.heygen.com/v3/avatars"
HEYGEN_LOOK_URL = "https://api.heygen.com/v3/avatars/looks/{look_id}"

HF_FLUX_MODEL = "black-forest-labs/FLUX.1-schnell"
HF_SDXL_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
DEFAULT_IMAGE_MODEL = "Hugging Face (FLUX Schnell, 자동 제공자)"

# UI 모델명 -> (provider, model_id)
# "자동 (무료 우선)"은 레거시 호환용이며, 다른 서비스로 넘어가지 않고 HF FLUX만 사용한다.
IMAGE_MODEL_CONFIG = {
    "Hugging Face (FLUX Schnell, 자동 제공자)": ("huggingface", HF_FLUX_MODEL),
    "Hugging Face (SDXL, 자동 제공자)": ("huggingface", HF_SDXL_MODEL),
    "자동 (무료 우선)": ("huggingface", HF_FLUX_MODEL),
    "ChatGPT (GPT Image 2)": ("openai", "gpt-image-2"),
    "ChatGPT (GPT Image 1.5)": ("openai", "gpt-image-1.5"),
    "ChatGPT (GPT Image 1)": ("openai", "gpt-image-1"),
    "ChatGPT (GPT Image 1 Mini)": ("openai", "gpt-image-1-mini"),
    "Kling (Text-to-Image)": ("kling", "kling-v2-1"),
    "HeyGen (Prompt-to-Avatar)": ("heygen", "prompt"),
    "Pollinations (크레딧, Z-Image)": ("pollinations", "zimage"),
    "Pollinations (크레딧, Klein)": ("pollinations", "klein"),
    "Pollinations (API 키)": ("pollinations", "zimage"),
    # 구 UI 이름 호환
    "Hugging Face (무료, SDXL)": ("huggingface", HF_SDXL_MODEL),
    "Hugging Face (무료, FLUX Schnell)": ("huggingface", HF_FLUX_MODEL),
    "Gemini 3.1 Flash Image": ("gemini", "gemini-3.1-flash-image"),
    "Gemini 2.5 Flash Image": ("gemini", "gemini-2.5-flash-image"),
    # 구 config.json 호환
    "Pollinations (무료, Flux)": ("pollinations", "zimage"),
    "Pollinations (무료, Z-Image)": ("pollinations", "zimage"),
    "Pollinations (무료, Klein)": ("pollinations", "klein"),
    "Imagen 4 Fast Generate": ("gemini", "gemini-2.5-flash-image"),
    "Imagen 4 Generate": ("gemini", "gemini-2.5-flash-image"),
    "Imagen 4 Ultra Generate": ("gemini", "gemini-2.5-flash-image"),
}

# 잔액 부족·할당량 초과가 확인된 서비스는 일정 시간 동안 호출하지 않는다.
PROVIDER_COOLDOWN_SEC = 3 * 60 * 60
_PROVIDER_COOLDOWN = {}

NO_TEXT_NEGATIVE_PROMPT = (
    "text, letters, words, typography, font, captions, subtitles, title, headline, "
    "watermark, logo, signage, banner, label, speech bubble, chart labels, axis labels, "
    "numbers, alphanumeric, korean text, english text, chinese characters, newspaper text, "
    "infographic text, UI text, buttons with text, readable writing, named brand logos"
)

NO_TEXT_PROMPT_SUFFIX = (
    " Absolutely no text, no letters, no numbers, no captions, no watermarks, "
    "no logos, no signs with writing anywhere in the image."
)


def _prepare_image_prompt(prompt_text: str) -> str:
    """텍스트 유도 표현을 제거하고, 무텍스트 지시를 프롬프트 끝에 보강한다."""
    cleaned = prompt_text.strip()
    remove_patterns = [
        r"\bwith (the )?(title|headline|text|caption|label|sign|banner|subtitle)[^.,\n]*",
        r"\b(saying|reading|displaying|showing) ['\"][^'\"]+['\"]",
        r"\btext overlay\b",
        r"\bKorean text\b",
        r"\bEnglish text\b",
        r"\blabeled chart\b",
        r"\binfographic with text\b",
    ]
    for pattern in remove_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.")
    if "no text" not in cleaned.lower():
        cleaned += NO_TEXT_PROMPT_SUFFIX
    return cleaned


def _save_image_bytes(base_filename: str, img_bytes: bytes) -> str:
    os.makedirs(IMAGES_DIR, exist_ok=True)
    filepath = os.path.join(IMAGES_DIR, f"{base_filename}.png")
    with open(filepath, "wb") as f:
        f.write(img_bytes)
    return filepath


def _save_image_response(base_filename: str, resp: requests.Response) -> str:
    content_type = resp.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        raise ValueError(f"이미지가 아닌 응답 ({content_type}): {resp.text[:200]}")
    return _save_image_bytes(base_filename, resp.content)


def _create_local_fallback_thumbnail(base_filename: str, title_text: str = "",
                                     label: str = "") -> str:
    """외부 이미지 API를 쓸 수 없을 때 제목을 얹은 썸네일을 직접 만든다."""
    os.makedirs(IMAGES_DIR, exist_ok=True)
    filepath = os.path.join(IMAGES_DIR, f"{base_filename}.png")
    return thumbnail_maker.create_thumbnail(filepath, title_text, label)


def _is_hf_token(key: str) -> bool:
    return key.startswith("hf_")


def _is_pollinations_key(key: str) -> bool:
    return key.startswith("sk_") or key.startswith("pk_")


def _is_openai_key(key: str) -> bool:
    return key.startswith("sk-") and not key.startswith("sk_")


def _is_gemini_key(key: str) -> bool:
    return key.startswith("AIza")


def _parse_kling_credentials(raw: str) -> tuple[str, str]:
    """Kling 키는 '액세스키:시크릿키' 또는 '액세스키|시크릿키' 형식."""
    raw = (raw or "").strip()
    for sep in (":", "|", ";"):
        if sep in raw:
            left, right = raw.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right
    return "", ""


def _pick_keys(api_key: str, fallback_api_key: str) -> dict:
    """API 키 종류별로 분류."""
    keys = {
        "pollinations": "",
        "huggingface": "",
        "gemini": "",
        "openai": "",
        "heygen": "",
        "kling": "",
    }
    for key in (api_key, fallback_api_key):
        if not key:
            continue
        if _is_hf_token(key) and not keys["huggingface"]:
            keys["huggingface"] = key
        elif _is_pollinations_key(key) and not keys["pollinations"]:
            keys["pollinations"] = key
        elif _is_openai_key(key) and not keys["openai"]:
            keys["openai"] = key
        elif _is_gemini_key(key) and not keys["gemini"]:
            keys["gemini"] = key
        elif _parse_kling_credentials(key)[0] and not keys["kling"]:
            keys["kling"] = key
        elif not keys["heygen"] and not _is_hf_token(key) and not _is_openai_key(key):
            # HeyGen 등 형식 구분이 애매한 키
            keys["heygen"] = key
        elif not keys["gemini"]:
            keys["gemini"] = key
    return keys


def _assign_selected_provider_key(keys: dict, provider: str, api_key: str,
                                  fallback_api_key: str = "") -> dict:
    """선택된 provider에 맞는 키가 비어 있으면 입력값을 그대로 할당한다."""
    candidates = [k for k in (api_key, fallback_api_key) if k]
    if not candidates:
        return keys

    if provider == "openai" and not keys.get("openai"):
        for c in candidates:
            if _is_openai_key(c):
                keys["openai"] = c
                return keys
        keys["openai"] = candidates[0]

    elif provider == "heygen" and not keys.get("heygen"):
        keys["heygen"] = candidates[0]

    elif provider == "kling" and not keys.get("kling"):
        for c in candidates:
            if _parse_kling_credentials(c)[0]:
                keys["kling"] = c
                return keys
        keys["kling"] = candidates[0]

    elif provider == "huggingface" and not keys.get("huggingface"):
        for c in candidates:
            if _is_hf_token(c):
                keys["huggingface"] = c
                return keys

    elif provider == "gemini" and not keys.get("gemini"):
        for c in candidates:
            if _is_gemini_key(c):
                keys["gemini"] = c
                return keys
        keys["gemini"] = candidates[0]

    elif provider == "pollinations" and not keys.get("pollinations"):
        for c in candidates:
            if _is_pollinations_key(c):
                keys["pollinations"] = c
                return keys

    return keys


def _extract_image_bytes_from_gemini_response(data: dict) -> bytes:
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini API 응답에 candidates가 없습니다.")

    parts = candidates[0].get("content", {}).get("parts", [])
    image_b64 = None
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            image_b64 = inline["data"]

    if not image_b64:
        raise ValueError("Gemini API 응답에 이미지 데이터가 없습니다.")

    return base64.b64decode(image_b64)


def _pollinations_headers(api_key: str) -> dict:
    headers = {"User-Agent": "nate-news-bot/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _call_pollinations_gen(prompt_text: str, model_id: str, api_key: str,
                           base_filename: str, log=print) -> str:
    """Pollinations 신규 gen.pollinations.ai 엔드포인트."""
    encoded_prompt = urllib.parse.quote(prompt_text.strip(), safe="")
    url = POLLINATIONS_GEN_URL.format(prompt=encoded_prompt)
    params = {
        "model": model_id,
        "width": 1280,
        "height": 720,
        "nologo": "true",
    }

    resp = requests.get(
        url, params=params, timeout=120,
        headers=_pollinations_headers(api_key),
    )
    if resp.ok:
        return _save_image_response(base_filename, resp)

    log(f"[이미지생성] Pollinations GET 오류 ({resp.status_code}): {resp.text[:300]}")

    if not api_key:
        resp.raise_for_status()

    payload = {
        "prompt": prompt_text.strip(),
        "model": model_id,
        "size": "1280x720",
        "response_format": "b64_json",
        "nologo": True,
    }
    resp = requests.post(
        POLLINATIONS_GEN_OPENAI_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if not resp.ok:
        log(f"[이미지생성] Pollinations POST 오류 ({resp.status_code}): {resp.text[:300]}")
    resp.raise_for_status()
    data = resp.json()
    item = data["data"][0]
    if item.get("b64_json"):
        return _save_image_bytes(base_filename, base64.b64decode(item["b64_json"]))
    if item.get("url"):
        img_resp = requests.get(item["url"], timeout=60)
        img_resp.raise_for_status()
        return _save_image_response(base_filename, img_resp)
    raise ValueError("Pollinations API 응답에 이미지 데이터가 없습니다.")


def _call_pollinations_legacy(prompt_text: str, model_id: str, api_key: str,
                              base_filename: str, log=print) -> str:
    """Pollinations 구형 image.pollinations.ai (키 없이 zimage/klein 시도용)."""
    encoded_prompt = urllib.parse.quote(prompt_text.strip(), safe="")
    url = POLLINATIONS_LEGACY_URL.format(prompt=encoded_prompt)
    params = {"model": model_id, "width": 1280, "height": 720, "nologo": "true"}
    if api_key:
        params["key"] = api_key

    resp = requests.get(
        url, params=params, timeout=120,
        headers=_pollinations_headers(api_key),
    )
    if not resp.ok:
        log(f"[이미지생성] Pollinations(legacy) 오류 ({resp.status_code}): {resp.text[:300]}")
    resp.raise_for_status()
    return _save_image_response(base_filename, resp)


def _hf_fetch_image_bytes(client, prompt_text: str, model_id: str,
                          negative_prompt: str | None = None,
                          width: int = 1280, height: int = 720) -> bytes:
    """HF Inference API에서 이미지 bytes를 받는다.

    exe(PyInstaller) 환경에서는 importlib.metadata로 Pillow를 못 찾아
    client.text_to_image()가 실패하므로, post-process 없이 bytes만 받는다.
    """
    from huggingface_hub.inference._providers import get_provider_helper

    provider_helper = get_provider_helper(client.provider, task="text-to-image", model=model_id)
    request_parameters = provider_helper.prepare_request(
        inputs=prompt_text.strip(),
        parameters={
            "negative_prompt": negative_prompt,
            "height": height,
            "width": width,
        },
        headers=client.headers,
        model=model_id,
        api_key=client.token,
    )
    response = client._inner_post(request_parameters)
    return provider_helper.get_response(response, request_parameters)


def _call_huggingface(prompt_text: str, api_key: str, model_id: str,
                      base_filename: str, log=print) -> str:
    """Hugging Face Inference Providers (provider=auto, hf_ 토큰 필요).

    fal-ai / together / hf-inference 등 사용 가능한 제공자를 HF가 자동 선택한다.
    """
    client = InferenceClient(api_key=api_key, provider="auto")
    log(f"[이미지생성] Hugging Face Inference Providers (auto) → {model_id}")

    try:
        img_bytes = _hf_fetch_image_bytes(
            client,
            prompt_text,
            model_id,
            negative_prompt=NO_TEXT_NEGATIVE_PROMPT,
            width=1280,
            height=720,
        )
    except HfHubHTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", "?")
        log(f"[이미지생성] Hugging Face API 오류 ({status}): {str(exc)[:300]}")
        raise ValueError(str(exc)) from exc

    os.makedirs(IMAGES_DIR, exist_ok=True)
    filepath = os.path.join(IMAGES_DIR, f"{base_filename}.png")
    try:
        from io import BytesIO
        image = Image.open(BytesIO(img_bytes))
        if image.size != (1280, 720):
            image = image.resize((1280, 720), Image.LANCZOS)
        image.save(filepath, "PNG", optimize=True)
    except Exception:
        return _save_image_bytes(base_filename, img_bytes)
    return filepath


def _call_openai_dalle(prompt_text: str, api_key: str, model: str,
                       base_filename: str, log=print) -> str:
    """OpenAI Images API — GPT Image / DALL·E 계열."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "prompt": prompt_text,
        "n": 1,
    }
    if str(model).startswith("gpt-image"):
        # 16:9에 가까운 가로형 (썸네일용)
        payload["size"] = "1536x1024"
        payload["quality"] = "medium"
    else:
        payload["size"] = "1024x1024"

    log(f"[이미지생성] OpenAI Images API → {model}")
    resp = requests.post(OPENAI_IMAGE_API_URL, headers=headers, json=payload, timeout=180)
    if not resp.ok:
        log(f"[이미지생성] OpenAI API 오류 ({resp.status_code}): {resp.text[:300]}")
    resp.raise_for_status()
    data = resp.json()
    item = data["data"][0]

    if item.get("b64_json"):
        return _save_image_bytes(base_filename, base64.b64decode(item["b64_json"]))
    if item.get("url"):
        img_resp = requests.get(item["url"], timeout=60)
        img_resp.raise_for_status()
        return _save_image_response(base_filename, img_resp)
    raise ValueError("OpenAI 응답에 이미지 데이터가 없습니다.")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _kling_jwt(access_key: str, secret_key: str) -> str:
    """Kling Access/Secret Key로 HS256 JWT 생성 (PyJWT 없이 stdlib만 사용)."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    payload = _b64url(json.dumps(
        {"iss": access_key, "exp": now + 1800, "nbf": now - 5},
        separators=(",", ":"),
    ).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = hmac.new(secret_key.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def _call_kling(prompt_text: str, credentials: str, model_id: str,
                base_filename: str, log=print) -> str:
    """Kling Text-to-Image (비동기 태스크 → 폴링)."""
    access_key, secret_key = _parse_kling_credentials(credentials)
    if not access_key or not secret_key:
        raise ValueError("Kling API 키는 '액세스키:시크릿키' 형식으로 입력하세요.")

    token = _kling_jwt(access_key, secret_key)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model_name": model_id or "kling-v2-1",
        "prompt": prompt_text.strip()[:2500],
        "negative_prompt": NO_TEXT_NEGATIVE_PROMPT[:2500],
        "n": 1,
        "aspect_ratio": "16:9",
    }
    log(f"[이미지생성] Kling Text-to-Image → {payload['model_name']}")
    resp = requests.post(KLING_IMAGE_API_URL, headers=headers, json=payload, timeout=60)
    if not resp.ok:
        log(f"[이미지생성] Kling API 오류 ({resp.status_code}): {resp.text[:300]}")
    resp.raise_for_status()
    body = resp.json()
    code = body.get("code")
    if code is not None and code not in (0, "0"):
        raise ValueError(f"Kling 태스크 생성 실패: {body.get('message') or body}")

    data = body.get("data") or {}
    task_id = data.get("task_id")
    if not task_id:
        raise ValueError(f"Kling 응답에 task_id가 없습니다: {body}")

    poll_url = f"{KLING_IMAGE_API_URL}/{task_id}"
    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(4)
        poll = requests.get(poll_url, headers=headers, timeout=60)
        if not poll.ok:
            log(f"[이미지생성] Kling 폴링 오류 ({poll.status_code}): {poll.text[:200]}")
            poll.raise_for_status()
        pdata = poll.json().get("data") or {}
        status = pdata.get("task_status") or pdata.get("status") or ""
        if status in ("succeed", "success", "completed"):
            images = ((pdata.get("task_result") or {}).get("images")) or []
            if not images:
                raise ValueError("Kling 결과에 이미지가 없습니다.")
            img_url = images[0].get("url")
            if not img_url:
                raise ValueError("Kling 결과에 이미지 URL이 없습니다.")
            img_resp = requests.get(img_url, timeout=60)
            img_resp.raise_for_status()
            return _save_image_response(base_filename, img_resp)
        if status in ("failed", "error"):
            raise ValueError(f"Kling 생성 실패: {pdata}")
        log(f"[이미지생성] Kling 생성 중... ({status or 'processing'})")

    raise TimeoutError("Kling 이미지 생성 대기 시간 초과")


def _call_heygen(prompt_text: str, api_key: str, base_filename: str, log=print) -> str:
    """HeyGen Prompt-to-Avatar로 이미지를 만들고 preview_image_url을 저장한다."""
    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
    }
    short_prompt = prompt_text.strip()[:1000]
    payload = {
        "type": "prompt",
        "name": f"thumb_{base_filename}"[:60],
        "prompt": short_prompt,
    }
    log("[이미지생성] HeyGen Prompt-to-Avatar 요청...")
    resp = requests.post(HEYGEN_AVATARS_URL, headers=headers, json=payload, timeout=90)
    if not resp.ok:
        log(f"[이미지생성] HeyGen API 오류 ({resp.status_code}): {resp.text[:300]}")
    resp.raise_for_status()
    data = (resp.json().get("data") or {})
    avatar_item = data.get("avatar_item") or {}
    look_id = avatar_item.get("id")
    preview = avatar_item.get("preview_image_url") or ""
    status = (avatar_item.get("status") or "").lower()
    if not look_id and not preview:
        raise ValueError(f"HeyGen 응답에 avatar/look 정보가 없습니다: {resp.text[:300]}")

    deadline = time.time() + 180
    while time.time() < deadline:
        if status in ("failed", "rejected", "error"):
            raise ValueError(f"HeyGen 아바타 생성 실패: {status}")
        if preview and status in ("completed", "complete", "ready"):
            break
        if preview and not look_id:
            break

        time.sleep(4)
        if not look_id:
            break

        poll = requests.get(HEYGEN_LOOK_URL.format(look_id=look_id), headers=headers, timeout=60)
        if not poll.ok:
            log(f"[이미지생성] HeyGen 폴링 오류 ({poll.status_code}): {poll.text[:200]}")
            if preview:
                break
            poll.raise_for_status()

        look = poll.json().get("data") or poll.json()
        if isinstance(look, dict) and "avatar_item" in look:
            look = look["avatar_item"]
        if isinstance(look, dict):
            status = (look.get("status") or status or "").lower()
            preview = look.get("preview_image_url") or preview
        log(f"[이미지생성] HeyGen 생성 중... ({status or 'processing'})")
        if preview and status in ("completed", "complete", "ready", ""):
            # status가 비어 있어도 preview가 생기면 사용
            if status in ("completed", "complete", "ready") or (
                preview and status not in ("processing", "pending", "queued")
            ):
                break

    if not preview:
        raise ValueError("HeyGen preview_image_url을 받지 못했습니다.")

    img_resp = requests.get(preview, timeout=60)
    img_resp.raise_for_status()
    return _save_image_response(base_filename, img_resp)


def _call_gemini_image(prompt_text: str, api_key: str, model_id: str,
                       base_filename: str, log=print) -> str:
    url = GEMINI_GENERATE_URL.format(model_id=model_id)
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "16:9"},
        },
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if not resp.ok:
        log(f"[이미지생성] Gemini API 오류 ({resp.status_code}): {resp.text[:300]}")
    resp.raise_for_status()
    img_bytes = _extract_image_bytes_from_gemini_response(resp.json())
    return _save_image_bytes(base_filename, img_bytes)


def _dispatch(provider: str, model_id: str, prompt_text: str, keys: dict,
              base_filename: str, log=print) -> str:
    """provider별 이미지 생성 호출."""
    if provider == "pollinations":
        poll_key = keys.get("pollinations", "")
        if poll_key:
            return _call_pollinations_gen(prompt_text, model_id, poll_key, base_filename, log)
        try:
            return _call_pollinations_gen(prompt_text, model_id, "", base_filename, log)
        except Exception:
            return _call_pollinations_legacy(prompt_text, model_id, "", base_filename, log)

    if provider == "huggingface":
        hf_key = keys.get("huggingface", "")
        if not hf_key:
            raise ValueError("Hugging Face 토큰(hf_...)이 필요합니다.")
        return _call_huggingface(prompt_text, hf_key, model_id, base_filename, log)

    if provider == "gemini":
        gemini_key = keys.get("gemini", "")
        if not gemini_key:
            raise ValueError("Google AI API 키가 필요합니다.")
        return _call_gemini_image(prompt_text, gemini_key, model_id, base_filename, log)

    if provider == "openai":
        openai_key = keys.get("openai", "")
        if not openai_key:
            raise ValueError("OpenAI(ChatGPT) API 키(sk-...)가 필요합니다.")
        return _call_openai_dalle(prompt_text, openai_key, model_id, base_filename, log)

    if provider == "kling":
        kling_cred = keys.get("kling", "")
        if not kling_cred:
            raise ValueError("Kling API 키(액세스키:시크릿키)가 필요합니다.")
        return _call_kling(prompt_text, kling_cred, model_id, base_filename, log)

    if provider == "heygen":
        heygen_key = keys.get("heygen", "")
        if not heygen_key:
            raise ValueError("HeyGen API 키가 필요합니다.")
        return _call_heygen(prompt_text, heygen_key, base_filename, log)

    raise ValueError(f"알 수 없는 provider: {provider}")


def _is_unrecoverable(error_text: str) -> bool:
    """잔액 부족·할당량 초과·인증 실패는 재시도해도 결과가 같다."""
    lowered = error_text.lower()
    return any(token in lowered for token in
               ("402", "401", "403", "404", "410", "429", "payment required",
                "insufficient balance", "quota", "too many requests",
                "unauthorized", "not found", "deprecated", "no longer supported",
                "rate limit", "credit", "balance"))


def _cooldown_remaining(provider: str) -> float:
    return max(0.0, _PROVIDER_COOLDOWN.get(provider, 0.0) - time.time())


def _provider_needs_key(provider: str) -> bool:
    return provider in ("huggingface", "gemini", "openai", "kling", "heygen")


def generate_thumbnail(prompt_text: str, api_key: str, model: str,
                       base_filename: str, log=print, max_retries: int = 2,
                       fallback_api_key: str = "", title_text: str = "",
                       label: str = "") -> str:
    """
    이미지 프롬프트로 썸네일을 생성해 png로 저장하고 파일 경로를 반환.
    선택한 모델이 한도 소진·실패하면 다른 모델로 넘기지 않고
    제목을 얹은 텍스트 썸네일을 만들어 반환한다.
    """
    os.makedirs(IMAGES_DIR, exist_ok=True)
    keys = _pick_keys(api_key, fallback_api_key)
    provider, model_id = IMAGE_MODEL_CONFIG.get(
        model, IMAGE_MODEL_CONFIG[DEFAULT_IMAGE_MODEL]
    )
    keys = _assign_selected_provider_key(keys, provider, api_key, fallback_api_key)

    if not prompt_text.strip():
        log("[이미지생성] 이미지 프롬프트가 비어 있어 제목 썸네일로 대체합니다.")
        return _create_local_fallback_thumbnail(base_filename, title_text, label)

    prompt_text = _prepare_image_prompt(prompt_text)

    # 키 필요 모델인데 키가 없으면 → 텍스트 썸네일 (다른 모델로 전환하지 않음)
    if _provider_needs_key(provider):
        key_map = {
            "huggingface": keys.get("huggingface"),
            "gemini": keys.get("gemini"),
            "openai": keys.get("openai"),
            "kling": keys.get("kling"),
            "heygen": keys.get("heygen"),
        }
        if not key_map.get(provider):
            log(f"[이미지생성] {provider} API 키가 없어 제목 썸네일을 만듭니다. "
                f"(다른 모델로 자동 전환하지 않습니다)")
            return _create_local_fallback_thumbnail(base_filename, title_text, label)

    remaining = _cooldown_remaining(provider)
    if remaining > 0:
        log(f"[이미지생성] {provider}는 한도 초과로 {int(remaining / 60)}분간 "
            f"건너뛰고 제목 썸네일을 만듭니다. (다른 모델로 자동 전환하지 않습니다)")
        return _create_local_fallback_thumbnail(base_filename, title_text, label)

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            log(f"[이미지생성] {provider}/{model_id} 시도 {attempt}/{max_retries}...")
            filepath = _dispatch(provider, model_id, prompt_text, keys, base_filename, log)
            if filepath:
                log(f"[이미지생성] 썸네일 저장 완료: {filepath}")
                return filepath
        except Exception as e:
            last_err = e
            log(f"[이미지생성] {provider}/{model_id} 실패: {e}")
            if _is_unrecoverable(str(e)):
                _PROVIDER_COOLDOWN[provider] = time.time() + PROVIDER_COOLDOWN_SEC
                log(f"[이미지생성] {provider} 한도/인증 문제로 재시도하지 않고 "
                    f"제목 썸네일로 대체합니다.")
                break
            if attempt < max_retries:
                time.sleep(3)

    log(f"[이미지생성] 외부 API 실패({last_err}) — 제목 썸네일로 대체합니다. "
        f"(다른 모델로 자동 전환하지 않습니다)")
    return _create_local_fallback_thumbnail(base_filename, title_text, label)
