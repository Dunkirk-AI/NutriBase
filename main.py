import base64
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompt.txt"
RECORDS_PATH = BASE_DIR / "records.json"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
RATIO_TOLERANCE = 0.05
RECORDS_LOCK = threading.Lock()

load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="NutriBase", version="0.1.0")


class FoodEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    weight_g: float = Field(ge=0, allow_inf_nan=False)
    calories_kcal: float = Field(ge=0, allow_inf_nan=False)
    protein_g: float = Field(ge=0, allow_inf_nan=False)
    fat_g: float = Field(ge=0, allow_inf_nan=False)
    carbs_g: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class ModelNutritionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    foods: list[FoodEstimate] = Field(min_length=1)
    estimated: Literal[True]


def _write_records_unlocked(records: list[dict]) -> None:
    temp_path = RECORDS_PATH.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, RECORDS_PATH)


def _read_records_unlocked() -> list[dict]:
    if not RECORDS_PATH.exists():
        _write_records_unlocked([])
        return []

    try:
        with RECORDS_PATH.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("records.json is unreadable or invalid") from exc

    if not isinstance(records, list):
        raise RuntimeError("records.json must contain a JSON array")
    return records


def _append_record(report: dict) -> None:
    with RECORDS_LOCK:
        records = _read_records_unlocked()
        records.append(report)
        _write_records_unlocked(records)


def _detect_image_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


async def _read_valid_image(file: UploadFile) -> tuple[bytes, str]:
    data = await file.read(MAX_IMAGE_BYTES + 1)
    await file.close()

    if not data:
        raise HTTPException(status_code=400, detail="Image file is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the 10 MiB limit")

    media_type = _detect_image_type(data)
    if media_type is None:
        raise HTTPException(status_code=400, detail="Only valid JPG and PNG images are accepted")
    return data, media_type


def _load_prompt() -> str:
    try:
        prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HTTPException(status_code=500, detail="prompt.txt could not be read") from exc
    if not prompt:
        raise HTTPException(status_code=500, detail="prompt.txt is empty")
    return prompt


async def _call_deepseek(image: bytes, media_type: str, weight_g: float) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="DEEPSEEK_API_KEY is not configured")

    prompt = _load_prompt()
    encoded_image = base64.b64encode(image).decode("ascii")
    request_body = {
        "model": "deepseek-flash",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"{prompt}\n\n本次食物总重量：{weight_g:g} g。",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{encoded_image}",
                            "detail": "original",
                        },
                    },
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "max_tokens": 2048,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(DEEPSEEK_URL, headers=headers, json=request_body)
            response.raise_for_status()
            payload = response.json()
        choice = payload["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("DeepSeek response was incomplete")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("DeepSeek returned empty content")
        return content
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="DeepSeek API rejected the request") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="DeepSeek API is unavailable") from exc
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="DeepSeek returned an invalid response") from exc


def _validate_model_report(content: str, total_weight_g: float) -> ModelNutritionResponse:
    try:
        result = ModelNutritionResponse.model_validate_json(content)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="DeepSeek returned invalid nutrition JSON") from exc

    ratio_sum = sum(food.ratio for food in result.foods)
    if abs(ratio_sum - 1.0) > RATIO_TOLERANCE:
        raise HTTPException(status_code=502, detail="Food ratios do not sum to approximately 1")

    reported_weight = sum(food.weight_g for food in result.foods)
    weight_tolerance = max(2.0, total_weight_g * RATIO_TOLERANCE)
    if abs(reported_weight - total_weight_g) > weight_tolerance:
        raise HTTPException(status_code=502, detail="Food weights do not match the submitted total")
    return result


def _build_report(result: ModelNutritionResponse, weight_g: float) -> dict:
    foods = [food.model_dump() for food in result.foods]
    total = {
        "calories_kcal": round(sum(food.calories_kcal for food in result.foods), 2),
        "protein_g": round(sum(food.protein_g for food in result.foods), 2),
        "fat_g": round(sum(food.fat_g for food in result.foods), 2),
        "carbs_g": round(sum(food.carbs_g for food in result.foods), 2),
    }
    return {
        "id": f"meal_{uuid.uuid4().hex}",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "weight_g": weight_g,
        "foods": foods,
        "total": total,
        "estimated": True,
    }


@app.post("/analyze")
async def analyze(
    file: Annotated[UploadFile, File(description="JPG or PNG food image")],
    weight_g: Annotated[float, Form(gt=0, allow_inf_nan=False)],
) -> dict:
    image, media_type = await _read_valid_image(file)
    model_content = await _call_deepseek(image, media_type, weight_g)
    model_report = _validate_model_report(model_content, weight_g)
    report = _build_report(model_report, weight_g)
    try:
        _append_record(report)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail="Report could not be saved") from exc
    return report


@app.get("/reports")
def get_reports() -> list[dict]:
    try:
        with RECORDS_LOCK:
            return _read_records_unlocked()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail="Reports could not be read") from exc
