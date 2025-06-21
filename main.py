from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import sys
import json
import re
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Form, Depends, Security
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, validator
import uvicorn
from fastapi.security import APIKeyHeader

app = FastAPI(
    title="YouTube 자막 추출기", 
    description="YouTube 영상의 자막을 추출하는 API",
    swagger_ui_parameters={"persistAuthorization": True}  # Swagger UI 인증 유지
)

# --- 보안 설정 ---
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# 여기에 유효한 API 키들을 추가하세요.
# 실제 프로덕션 환경에서는 환경 변수나 보안 저장소에서 불러오는 것이 안전합니다.
VALID_API_KEYS = {
    "n8n-example-admin",
    "n8n-example-0001"  # 사용자가 사용하려는 키 추가
}

async def get_api_key(api_key: str = Security(api_key_header)):
    """API 키를 헤더에서 검증하고, 없거나 틀리면 오류를 반환합니다."""
    if api_key is None:
        raise HTTPException(
            status_code=401,  # 401 Unauthorized
            detail="API key is missing. Please include 'X-API-Key' in the request header."
        )
    
    # .strip()으로 복사/붙여넣기 시 발생할 수 있는 공백 제거
    if api_key.strip() in VALID_API_KEYS:
        return api_key.strip()
    else:
        raise HTTPException(
            status_code=403,  # 403 Forbidden
            detail="Invalid API Key. Access is denied."
        )
# --- 보안 설정 끝 ---

# 템플릿 설정
templates = Jinja2Templates(directory="templates")

class VideoRequest(BaseModel):
    video_id: str
    languages: list[str] = ['ko', 'en']
    
    @validator('video_id')
    def validate_video_id(cls, v):
        if not v or not v.strip():
            raise ValueError("video_id는 필수입니다.")
        
        # YouTube URL에서 video_id 추출
        if 'youtube.com' in v or 'youtu.be' in v:
            # youtube.com/watch?v=VIDEO_ID
            if 'youtube.com/watch?v=' in v:
                v = v.split('youtube.com/watch?v=')[1].split('&')[0]
            # youtu.be/VIDEO_ID
            elif 'youtu.be/' in v:
                v = v.split('youtu.be/')[1].split('?')[0]
        
        # video_id 형식 검증 (11자리 영숫자)
        if not re.match(r'^[a-zA-Z0-9_-]{11}$', v):
            raise ValueError("올바른 YouTube video_id 형식이 아닙니다.")
        
        return v

def get_transcript(video_id, languages=['ko', 'en']):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        return transcript
    except TranscriptsDisabled:
        raise Exception("해당 영상은 자막이 꺼져 있습니다.")
    except NoTranscriptFound:
        raise Exception("해당 언어의 자막이 없습니다.")
    except Exception as e:
        raise Exception(f"자막 추출 중 오류 발생: {str(e)}")

def process_transcript(transcript):
    if not transcript:
        raise Exception("자막 데이터가 비어있습니다.")
    
    # 텍스트 추출
    full_text = ' '.join([item['text'] for item in transcript])
    
    return {
        "text": full_text,
        "json": transcript,
        "word_count": len(full_text.split()),
        "duration": sum(item.get('duration', 0) for item in transcript)
    }

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/", response_class=HTMLResponse)
async def process_video(request: Request, video_id: str = Form(None)):
    if not video_id or not video_id.strip():
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "error": "YouTube URL 또는 Video ID를 입력해주세요."
        })
    
    try:
        # VideoRequest로 검증
        video_request = VideoRequest(video_id=video_id)
        transcript = get_transcript(video_request.video_id, video_request.languages)
        result = process_transcript(transcript)
        
        return templates.TemplateResponse("result.html", {
            "request": request,
            "video_id": video_request.video_id,
            "result": result
        })
        
    except Exception as e:
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "error": str(e)
        })

@app.post("/transcript", dependencies=[Depends(get_api_key)])
async def get_video_transcript(request: VideoRequest):
    try:
        transcript = get_transcript(request.video_id, request.languages)
        result = process_transcript(transcript)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

def main():
    if len(sys.argv) > 1:
        video_id = sys.argv[1]
    else:
        print("❌ video_id가 필요합니다.")
        print("사용법: python main.py <video_id>")
        return
    
    try:
        # VideoRequest로 검증
        video_request = VideoRequest(video_id=video_id)
        transcript = get_transcript(video_request.video_id)
        result = process_transcript(transcript)
        
        # 파일로 저장
        text_file = f"transcript_{video_request.video_id}.txt"
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(result["text"])
        
        json_file = f"transcript_{video_request.video_id}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(result["json"], f, ensure_ascii=False, indent=2)
        
        print(f"✅ 자막 추출 성공!")
        print(f"📝 텍스트 파일 저장: {text_file}")
        print(f"📊 JSON 파일 저장: {json_file}")
        print(f"📊 단어 수: {result['word_count']}")
        print(f"⏱️  총 길이: {result['duration']:.1f}초")
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        main()
