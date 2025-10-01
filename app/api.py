from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.s3_utils import fetch_png_from_s3
from app.highlighter import highlight_png
from app.config import config

app = FastAPI(title="PDF Highlighter API", version="1.0")

class HighlightRequest(BaseModel):
    file_id: str
    page_num: int
    polygons: list[list[list[int]]]  # List of polygons (points in image coords)

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/highlight")
def highlight_page(req: HighlightRequest):
    """
    Fetch a PNG from S3, apply polygon highlights, and return PNG binary.
    """
    key = f"output_images/{req.file_id}/page_{req.page_num}.png"

    try:
        img_buf = fetch_png_from_s3(key)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Page not found in S3: {key}")

    highlighted_buf = highlight_png(img_buf, req.polygons)

    return StreamingResponse(highlighted_buf, media_type="image/png")
