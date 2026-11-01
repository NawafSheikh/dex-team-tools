# Training video generator (Episode 5)

A Copilot Studio agent that turns an SOP, work instruction or policy into a finished internal training video:
title, overview, numbered steps on the document's own screenshots with highlights, tips and warnings, a recap,
captions, natural narration and a music bed. Rendered with HyperFrames (HTML compositions rendered to video).
No video model, no GPU.

Episode 5: "Copilot Studio makes training videos from your documents" (video coming).

## How it works

```
Word / PDF / text  ->  IngestDocument  ->  text with [image:imgN] markers + screenshots (OCR words)
                       (agent writes a scene plan from the document, following the training-video skill)
scene plan         ->  StartTrainingVideo  ->  validate  ->  narrate (Gemini TTS, per sentence)
                                           ->  compile to a HyperFrames project (deterministic)
                                           ->  render MP4, music bed ducked under the voice, -16 LUFS
GetTrainingVideo   ->  status, progress, then the MP4 and SRT links
```

The agent only plans. The service owns every pixel, voice and timing, so the same plan always produces the same
video. The plan schema is strict: a bad plan gets a 400 with a path for every broken rule, and the agent fixes
them itself (it did, twice, in our first live run). Highlights are pinned to the words on the screenshot by OCR.
If a label in the plan is not on the screenshot, the job finishes with a warning instead of drawing a box in the
wrong place.

## Layout

| Folder | What |
|---|---|
| `service/` | The render service (Node 22+): `server/` API, `tests/`, `openapi/` (Swagger 2.0 for the custom connector), `scripts/` (OCR pass for button labels, a re-render helper, a layout prototype) |
| `copilot/` | The Copilot Studio agent: `agent/` (instructions, the three tools, settings), `skills/training-video/SKILL.md` (structure rules for a good training video), `connector/` |
| `sample/` | A fictional company's expense app (Brightwater Expenses) and the scripts that screenshot it and build the SOP Word document the episode used |

## Run it

Requirements: Node 22+, ffmpeg and ffprobe, poppler (`pdftotext`, `pdfimages`) for PDFs, tesseract and Python 3
with numpy and Pillow for OCR, a Gemini API key for narration and music.

```bash
cd service
npm install
npm test                                  # 28 tests, no API calls
cp .env.example .env                      # set TV_PUBLIC_BASE and the key files
mkdir -p state && openssl rand -hex 32 > state/api-key && printf '%s' "$GEMINI_API_KEY" > state/gemini-key
set -a; . ./.env; set +a
npm start                                 # http://127.0.0.1:8913
```

| Method | Path | Use |
|---|---|---|
| POST | `/ingest` | `{fileName, fileBase64}` or `{text}`: returns `docId`, text with image markers, images with OCR words |
| POST | `/render` | `{docId, plan, brandName?, brandColor?, voice?}`: 202 with `jobId`, queue position, estimate |
| GET | `/jobs/{jobId}?waitSeconds=` | status, stage, progress; when done `videoUrl`, `captionsUrl`, timings, warnings |
| GET | `/v/{token}.mp4`, `/v/{token}.srt` | the finished video and captions (the random token in the link is the access check, no key) |
| GET | `/health`, `/openapi.json` | health, and the connector definition with your host filled in |

Every other call needs `x-api-key`. There are rate limits, one render at a time, a
short queue, and request logs that never contain bodies, documents or keys.

Sample document:

```bash
cd sample/sop
pip install playwright python-docx pillow && playwright install chromium
python capture.py && python make_sop.py   # real screenshots of the sample app, then the Word SOP
```

### Copilot Studio side

1. Import `copilot/connector/apiDefinition.swagger.json` (set `host` and `basePath` to yours, or download
   `/openapi.json` from your server) with `apiProperties.json` as a custom connector, and create a connection
   with your API key.
2. Create an agent, put `copilot/agent/agent.mcs.yml` (instructions plus the skill) and the three `actions/` in its
   workspace, point `connectionreferences.mcs.yml` and the actions at your connection reference, then
   `pac copilot push` and publish. Turn on file uploads so people can attach the SOP.
3. Attach an SOP in the chat and ask for a training video.

Two things we learned the hard way: curly braces in Copilot Studio instructions are read as Power Fx, so a
literal `{` must be written as `{Char(123)}`. And required connector inputs need `shouldPromptUser: true`, or
publishing fails.

## Measured on our runs

All renders on a shared 3-core server without a GPU, one render at a time.

| Run | Video | Render | Document to MP4 |
|---|---|---|---|
| SOP, 7 steps, 7 screenshots | 2:09 | 22.6 min | 24.3 min |
| From the Copilot test chat, Word file attached | 2:11 | 21.5 min | 25.7 min from pressing Send |

Third-party cost per 2-minute video at 2026 prices: about $0.03 narration plus $0.08 music, so about $0.11.
Copilot Studio ran on the standard harness without Copilot Credits.

## Honest limits

- Rendering is slow on a small CPU server: 10 to 17 minutes of render per minute of video on ours. A bigger
  machine is faster.
- Narration and music need a Gemini API key, and daily TTS quotas apply.
- The video is only as accurate as the document. The agent is told never to invent steps or button names, and
  the plan keeps the document's UI labels word for word, but check the result against the source before you
  publish it to staff.
- If Lyria music fails, the service uses `TV_FALLBACK_BED` or a silent bed rather than failing the video.
- Known gap (open): uploads are size-limited, but a Word file's decompressed size is not yet bounded while it is
  unpacked, so a crafted file from someone holding the API key could use a lot of memory. Keep the key private.
