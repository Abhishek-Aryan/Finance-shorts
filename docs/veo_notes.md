# Google Veo Video Generation API Notes (Gemini API)

## 1. Model IDs & Features
- **Recommended Model ID**: `veo-3.1-fast-generate-preview` (Fast generation, optimized latency and cost) or `veo-3.1-generate-preview` (Full cinematic quality).
- **Aspect Ratio**: Native support for `9:16` (vertical video portrait: 1080x1920 or 720x1280) and `16:9` (horizontal landscape).
- **Image-to-Video Conditioning**: Supported via reference images (`reference_images` / "Ingredients to video" in `GenerateVideosConfig`). Up to 3 reference images can steer characters or styles. When `assets/character/mentor_character_1.png` is provided, it can be passed as reference image conditioning.
- **Audio Generation**: Veo 3.1 models generate synchronized audio by default. To suppress unwanted sounds, negative prompts can include audio cues; regardless, the video composer explicitly strips/mutes generated video audio tracks so only Edge-TTS audio is mixed with the background score.

## 2. Request Shape & Long-Running Operation Pattern
- **Initiation Endpoint**:
  `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning`
- **Headers**:
  `x-goog-api-key: {GEMINI_API_KEY}`
  `Content-Type: application/json`
- **Request Body Shape**:
  ```json
  {
    "prompt": "Cinematic 8k portrait of an elite finance mentor in a dark luxury boardroom with gold accents...",
    "config": {
      "aspect_ratio": "9:16",
      "resolution": "720p",
      "negative_prompt": "blurry, low quality, distorted, watermark",
      "duration_seconds": 5
    }
  }
  ```
- **Operation Return**:
  Returns a JSON response representing the long-running operation:
  ```json
  {
    "name": "operations/models/veo-3.1-fast-generate-preview/operations/op_12345678"
  }
  ```
- **Polling Operation**:
  `GET https://generativelanguage.googleapis.com/v1beta/{operation_name}` with `x-goog-api-key: {GEMINI_API_KEY}`.
  Poll with exponential backoff (e.g., initial 10s-20s interval) until `"done": true`.
- **Result & Download URL Behavior**:
  When `"done": true`, the response payload contains `generated_videos` (or `generatedVideos`):
  ```json
  {
    "response": {
      "generatedVideos": [
        {
          "video": {
            "uri": "https://generativelanguage.googleapis.com/v1beta/files/file_abc123"
          }
        }
      ]
    }
  }
  ```
  **Critical**: The download URI requires authentication. Requests to download the raw MP4 stream must append `?key={GEMINI_API_KEY}` to the URL or pass the `x-goog-api-key` header, otherwise the API returns `401 Unauthorized`.

## 3. Clip Duration, Resolutions, and Limits
- **Clip Duration**: 5 to 8 seconds per generated clip.
- **Aspect Ratios**: `9:16` (vertical) and `16:9` (horizontal).
- **Resolution**: `720p` (720x1280 vertical), `1080p` (1080x1920 vertical), and `4k`.
- **Composer Mapping**: 6 scenes per topic, each requesting 5-6 seconds of video. Total raw video: ~30-36 seconds, perfectly aligning with `TARGET_DURATION_MIN` (30s) and `TARGET_DURATION_MAX` (60s).

## 4. Rate Limits & Pricing
- **Rate Limits**:
  - Preview models (`veo-3.1-fast-generate-preview`, `veo-3.1-generate-preview`): 10 Requests Per Minute (RPM) with max 10 concurrent requests per project.
  - Quota limit / 429 returns `RESOURCE_EXHAUSTED`.
- **Pricing**:
  - Veo 3.1 Fast: ~$0.10 / sec (720p), ~$0.12 / sec (1080p).
  - Veo 3.1 Standard: ~$0.40 / sec.
  - Veo 3.1 Lite: ~$0.05 / sec.
  - Per 30s video (6 scenes x 5s): ~$3.00 to ~$3.60 on Veo Fast.
- **Free-Tier Allowance**:
  - There is **no free tier** for Veo video generation on the Gemini API; all video seconds require active billing on Google Cloud / Google AI Studio.
- **Cost Guard Implementation**:
  - `VEO_MAX_SECONDS_PER_DAY` (default 60s)
  - `VEO_MAX_SECONDS_PER_RUN` (default 60s)
  - Ledger file: `data/usage_ledger.json`
  - If a run would exceed either cap, the provider halts before submission, returns Exit Code 5 ("budget cap reached"), and leaves the row in `Pending` without failing it.
