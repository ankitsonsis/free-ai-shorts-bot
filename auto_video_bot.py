#!/usr/bin/env python3
"""
100% Free Automated Faceless YouTube Shorts Generator & Uploader
Powered by:
1. Google Gemini API (Free Tier) - Script, Title, Description, Tags, Search Queries
2. Microsoft Edge TTS (edge-tts) - Free Natural Hindi/English Neural Voiceover + Subtitles (.srt)
3. Pexels Free Stock Video API - HD 9:16 Vertical Background Clips
4. FFmpeg - Cloud Video Assembly, Audio Mixing & Burned-In Subtitles
5. YouTube Data API v3 - Direct Automated Scheduled Uploading
"""

import os
import json
import random
import asyncio
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

import edge_tts
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# CONFIGURATION (Easily Changeable)
# ==========================================
# Choose your channel niche & voice
NICHE_TOPICS = [
    "Mysterious Unsolved Historical Facts in Hindi",
    "Mind-Blowing Space and Science Facts in Hindi",
    "Dark Psychology and Human Behavior Tricks in Hindi",
    "Ancient Indian Science and Temple Mysteries in Hindi",
    "Future AI and Technology Secrets in Hindi"
]

# Best Free Neural Voices in edge-tts:
# Hindi Male: "hi-IN-MadhurNeural"
# Hindi Female: "hi-IN-SwaraNeural"
# English Male: "en-US-ChristopherNeural"
VOICE_ID = os.environ.get("VOICE_ID", "hi-IN-MadhurNeural")
VOICE_RATE = "+10%"  # Slightly energetic pacing for high retention on Shorts

WORK_DIR = Path("output_build")
WORK_DIR.mkdir(exist_ok=True)


def generate_script_with_gemini(gemini_api_key: str) -> dict:
    """Uses Google Gemini API (Free Tier) to write a high-retention Shorts script and metadata."""
    client = genai.Client(api_key=gemini_api_key)
    chosen_niche = os.environ.get("CHANNEL_NICHE", random.choice(NICHE_TOPICS))

    prompt = f"""
    You are an expert viral YouTube Shorts scriptwriter.
    Write a 100% original, high-retention 45-to-55 second YouTube Short script for the niche: "{chosen_niche}".
    
    CRITICAL RULES FOR YOUTUBE MONETIZATION & RETENTION:
    - Start with a shocking 3-second hook question or statement.
    - Tell a specific, factual, verifiable story or explain a real phenomenon (NO generic repetitive fluff).
    - Write the spoken narration (`voiceover_text`) in natural conversational Hinglish/Hindi (written in Devanagari or clear Hindi words so Hindi TTS pronounces it naturally).
    - Provide 4 specific English search keywords (`pexels_queries`) for 9:16 vertical stock videos that match the visual mood of each part of the script.
    
    Return strictly valid JSON with these exact keys:
    {{
      "title": "Catchy viral title under 60 chars #shorts",
      "description": "Engaging description with #shorts #facts #hindi",
      "tags": ["shorts", "facts", "hindi", "mystery", "knowledge"],
      "voiceover_text": "Full spoken script in Hindi without any stage directions or brackets...",
      "pexels_queries": ["cinematic dark universe", "ancient temple mystery", "clock ticking fast", "glowing brain neural network"]
    }}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.8,
        ),
    )
    data = json.loads(response.text)
    print(f"[+] Script Generated: {data['title']}")
    return data


async def generate_voice_and_subtitles(text: str, audio_path: Path, srt_path: Path):
    """Generates free neural voiceover and word-level subtitles using Microsoft Edge TTS."""
    communicate = edge_tts.Communicate(text, VOICE_ID, rate=VOICE_RATE)
    submaker = edge_tts.SubMaker()

    with open(audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)

    with open(srt_path, "w", encoding="utf-8") as srt_file:
        srt_file.write(submaker.get_srt())

    print(f"[+] Audio & Subtitles saved to {audio_path} and {srt_path}")


def download_pexels_videos(pexels_api_key: str, queries: list, count_Needed: int = 4) -> list:
    """Downloads free HD vertical (9:16) stock videos from Pexels API."""
    downloaded_files = []
    headers = {"Authorization": pexels_api_key}

    for idx, query in enumerate(queries[:count_Needed]):
        encoded_query = urllib.parse.quote(query)
        url = f"https://api.pexels.com/videos/search?query={encoded_query}&orientation=portrait&size=medium&per_page=5"
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                videos = result.get("videos", [])
                if not videos:
                    continue

                video_choice = random.choice(videos)
                video_files = video_choice.get("video_files", [])
                # Prefer HD vertical mp4
                best_file = sorted(
                    [vf for vf in video_files if vf.get("file_type") == "video/mp4" and vf.get("height", 0) >= 1280],
                    key=lambda x: x.get("height", 0),
                )
                download_url = (best_file[0] if best_file else video_files[0])["link"]

                clip_path = WORK_DIR / f"clip_{idx}.mp4"
                urllib.request.urlretrieve(download_url, clip_path)
                downloaded_files.append(clip_path)
                print(f"[+] Downloaded Pexels B-Roll for '{query}' -> {clip_path}")
        except Exception as e:
            print(f"[!] Warning: Could not fetch Pexels clip for '{query}': {e}")

    if not downloaded_files:
        raise RuntimeError("No Pexels videos could be downloaded. Check your PEXELS_API_KEY.")
    return downloaded_files


def get_audio_duration(audio_path: Path) -> float:
    """Returns duration of the generated MP3 audio in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)
    ]
    output = subprocess.check_output(cmd).decode("utf-8").strip()
    return float(output)


def assemble_video_ffmpeg(clips: list, audio_path: Path, srt_path: Path, final_output: Path):
    """Normalizes B-roll clips to 1080x1920 30fps, loops/trims to match audio length, and burns subtitles."""
    total_duration = get_audio_duration(audio_path)
    segment_duration = total_duration / len(clips)

    normalized_clips = []
    for i, clip in enumerate(clips):
        norm_path = WORK_DIR / f"norm_{i}.mp4"
        cmd = [
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(clip),
            "-t", f"{segment_duration:.2f}",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            str(norm_path)
        ]
        subprocess.run(cmd, check=True)
        normalized_clips.append(norm_path)

    concat_list_path = WORK_DIR / "concat_list.txt"
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for norm_clip in normalized_clips:
            f.write(f"file '{norm_clip.resolve()}'\n")

    merged_bg = WORK_DIR / "merged_bg.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list_path), "-c", "copy", str(merged_bg)
    ], check=True)

    # Burn subtitles & attach voiceover audio
    subtitle_style = (
        "Fontname=Noto Sans Devanagari,Fontsize=18,PrimaryColour=&H0000FFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=60"
    )
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(merged_bg),
        "-i", str(audio_path),
        "-vf", f"subtitles={srt_path.as_posix()}:force_style='{subtitle_style}'",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(final_output)
    ], check=True)
    print(f"[+] Final Video Assembled: {final_output}")


def upload_to_youtube(video_path: Path, metadata: dict):
    """Uploads the finished MP4 directly to YouTube using OAuth2 Refresh Token."""
    client_id = os.environ.get("YT_CLIENT_ID")
    client_secret = os.environ.get("YT_CLIENT_SECRET")
    refresh_token = os.environ.get("YT_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        print("[!] YouTube OAuth secrets not set yet. Skipping auto-upload (video is saved in output_build/final_short.mp4).")
        return

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": metadata["title"][:100],
            "description": metadata["description"],
            "tags": metadata.get("tags", ["shorts", "facts"]),
            "categoryId": "27"  # Education / Knowledge
        },
        "status": {
            "privacyStatus": os.environ.get("YT_PRIVACY", "public"),
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True  # Complies with YouTube 2026 AI Disclosure Rules
        }
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print(f"[+] Successfully Uploaded to YouTube! Video ID: https://youtu.be/{response['id']}")


async def main():
    gemini_key = os.environ.get("GEMINI_API_KEY")
    pexels_key = os.environ.get("PEXELS_API_KEY")

    if not gemini_key or not pexels_key:
        raise ValueError("Missing GEMINI_API_KEY or PEXELS_API_KEY in environment variables!")

    # Step 1: Brain - Generate script & metadata with Gemini
    metadata = generate_script_with_gemini(gemini_key)

    # Step 2: Voice & Subtitles - Generate with Microsoft Edge TTS
    audio_path = WORK_DIR / "voiceover.mp3"
    srt_path = WORK_DIR / "subtitles.srt"
    await generate_voice_and_subtitles(metadata["voiceover_text"], audio_path, srt_path)

    # Step 3: Visuals - Fetch vertical HD stock footage from Pexels
    clips = download_pexels_videos(pexels_key, metadata["pexels_queries"])

    # Step 4: Render - Combine clips, audio, and subtitles via FFmpeg
    final_video = WORK_DIR / "final_short.mp4"
    assemble_video_ffmpeg(clips, audio_path, srt_path, final_video)

    # Step 5: Auto-Upload to YouTube
    upload_to_youtube(final_video, metadata)


if __name__ == "__main__":
    asyncio.run(main())