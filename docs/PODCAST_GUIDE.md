# Cram-It Podcast Generation Guide

Generate two-voice audio review podcasts and video podcasts with visual graphs from any Cram-It course pack. Students can listen on their commute, before bed, or as a complement to active drilling.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Script Format](#script-format)
5. [Auto-Generation with AI](#auto-generation-with-ai)
6. [Voice Selection](#voice-selection)
7. [Video Podcasts](#video-podcasts)
8. [Integration with Cram-It PWA](#integration-with-cram-it-pwa)
9. [Tips & Best Practices](#tips--best-practices)
10. [Troubleshooting](#troubleshooting)
11. [Full Walkthrough: Demo Study Skills Pack](#full-walkthrough-demo-study-skills-pack)

---

## Overview

The podcast system consists of three tools that work together:

| Tool | Purpose |
|------|---------|
| `tools/generate_podcast_script.py` | Uses Claude AI to generate a two-voice dialogue script from course pack content |
| `tools/generate_podcast.py` | Converts a script into an audio MP3 podcast using Edge-TTS |
| `tools/generate_podcast_video.py` | Creates an MP4 video podcast with synchronized text frames and optional graphs |

### What Gets Generated

- **Audio podcasts** (`.mp3`): A natural-sounding conversation between two AI voices — a tutor and a student — reviewing all key concepts from a course pack. Typically 8–15 minutes long.
- **Video podcasts** (`.mp4`): The same audio with synchronized visual frames showing the current speaker, dialogue text, concept highlights, and optionally matplotlib-rendered graphs/charts for quantitative topics.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Course Pack (concept_map.json + questions.json)        │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│  generate_podcast_script.py                             │
│  Claude API → Two-voice dialogue script (.txt)          │
└───────────────────────┬─────────────────────────────────┘
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
┌──────────────────────┐ ┌────────────────────────────────┐
│ generate_podcast.py  │ │ generate_podcast_video.py      │
│ Edge-TTS → .mp3      │ │ Edge-TTS + matplotlib + ffmpeg │
│                      │ │ → .mp4 with visual frames      │
└──────────┬───────────┘ └──────────────┬─────────────────┘
           │                            │
           ▼                            ▼
┌──────────────────────────────────────────────────────────┐
│  podcast/review.mp3  |  podcast/review_video.mp4        │
│  Served by Flask at /podcast/<filename>                  │
│  Played in the Podcast tab of the PWA                    │
└──────────────────────────────────────────────────────────┘
```

---

## Prerequisites

### Python Packages

Install the required dependencies:

```bash
pip install edge-tts anthropic matplotlib Pillow pydub
```

| Package | Version | Purpose |
|---------|---------|---------|
| `edge-tts` | >= 6.1 | Microsoft Edge text-to-speech (free, high-quality) |
| `anthropic` | >= 0.18 | Claude API for AI script generation |
| `matplotlib` | >= 3.7 | Rendering visual frames for video podcasts |
| `Pillow` | >= 10.0 | Image processing for video frames |
| `pydub` | >= 0.25 | Audio segment manipulation and concatenation |

### System Dependencies

**ffmpeg** is required for audio concatenation and video assembly:

```bash
# macOS (Homebrew)
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Arch Linux
sudo pacman -S ffmpeg

# Verify installation
ffmpeg -version
```

On macOS with Homebrew, ffmpeg is typically at `/opt/homebrew/bin/ffmpeg`. On Linux, it's usually on the PATH at `/usr/bin/ffmpeg`.

### API Keys

For AI-generated scripts, you need an Anthropic API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

This is only needed for `generate_podcast_script.py`. If you write scripts manually, no API key is required.

---

## Quick Start

Generate a complete audio podcast in three commands:

```bash
# 1. Generate a script from your course pack
python tools/generate_podcast_script.py \
  --pack packs/demo-study-skills \
  --output podcast/script.txt

# 2. Convert the script to audio
python tools/generate_podcast.py \
  --script podcast/script.txt \
  --output podcast/review.mp3

# 3. (Optional) Generate a video version with visual frames
python tools/generate_podcast_video.py \
  --script podcast/script.txt \
  --output podcast/review_video.mp4
```

That's it. Start the Cram-It server and the podcast appears in the **Pod** tab.

```bash
python server.py
# → Open http://localhost:3000 → tap the Pod tab
```

---

## Script Format

### The [VOICE1] / [VOICE2] Tag System

Podcast scripts use a simple tag-based format to indicate which speaker is talking. Each line begins with a speaker tag:

```
[VOICE1] Welcome to today's review session! We're going to cover all the key concepts you need for your upcoming exam on study skills.

[VOICE2] Sounds great. I've been studying but I feel like some of these concepts blend together. Can we start with spaced repetition?

[VOICE1] Absolutely. Spaced repetition is all about distributing your study sessions over time rather than cramming everything into one marathon session.

[VOICE2] So it's basically the opposite of pulling an all-nighter?

[VOICE1] Exactly. Research shows that spacing out your review with increasing intervals — say, after 1 day, then 3 days, then 7 days — dramatically improves long-term retention.
```

### Speaker Roles

| Tag | Default Role | Description |
|-----|-------------|-------------|
| `[VOICE1]` | Tutor / Host | Explains concepts, provides examples, corrects misconceptions |
| `[VOICE2]` | Student / Co-host | Asks questions, gives (sometimes wrong) answers, requests clarification |

### Writing Custom Scripts

You can write scripts entirely by hand. Rules:

1. **One speaker tag per paragraph.** Each `[VOICE1]` or `[VOICE2]` tag starts a new spoken segment.
2. **Keep segments natural length.** 1–4 sentences per segment works best. Too long and the listener loses track of who's speaking.
3. **No special characters in speech.** Avoid brackets, asterisks, or formatting within the spoken text — Edge-TTS reads them literally.
4. **Blank lines are ignored** between segments.
5. **Lines without tags are skipped** during parsing.

### Example: Custom Script File

```text
[VOICE1] Hey everyone, welcome back to the Cram-It review podcast. Today we're tackling organic chemistry mechanisms.

[VOICE2] Oh great, my favorite. I always mix up SN1 and SN2. Can you break down the difference?

[VOICE1] Sure. The key difference is the number of steps. SN2 is a one-step, concerted mechanism — the nucleophile attacks at the same time the leaving group departs. It's like a revolving door.

[VOICE2] And SN1 is two steps?

[VOICE1] Right. In SN1, the leaving group departs first to form a carbocation intermediate, and then the nucleophile attacks. Two separate steps.

[VOICE2] So if I see a tertiary substrate, I should think SN1 because of steric hindrance blocking the backside attack?

[VOICE1] Exactly. That's a great exam tip. Tertiary substrates strongly favor SN1 because the bulky groups prevent the concerted SN2 mechanism.
```

### Alternative Format: TUTOR / STUDENT Tags

The script parser also supports the older `TUTOR:` / `STUDENT:` format:

```text
TUTOR: Welcome to today's review session.
STUDENT: Thanks! I'm ready to dive in.
TUTOR: Let's start with the fundamentals.
```

Both formats are automatically detected and parsed correctly.

---

## Auto-Generation with AI

### How It Works

`generate_podcast_script.py` uses Claude to automatically create a natural, educational dialogue script from your course pack content. It reads:

1. **concept_map.json** — All concepts, descriptions, prerequisites, and keywords
2. **questions.json** — Sample questions from the exam bank (for context on what gets tested)
3. **pack.yaml** — Course name, exam format, and AI persona settings

### The Generation Process

```
concept_map.json ──┐
                    ├──→ Claude Prompt ──→ Two-Voice Script (.txt)
questions.json  ──┘      (Anthropic API)
pack.yaml ────────┘
```

Claude receives a structured prompt that includes:

- The full concept list with descriptions
- A sample of exam questions to understand testing style
- Instructions for the dialogue format
- Guidelines for educational podcast pacing

### Usage

```bash
# Basic usage — reads from a pack directory
python tools/generate_podcast_script.py \
  --pack packs/demo-study-skills \
  --output podcast/script.txt

# With custom duration target
python tools/generate_podcast_script.py \
  --pack packs/demo-study-skills \
  --output podcast/script.txt \
  --duration 15  # Target ~15 minutes

# With a specific Claude model
python tools/generate_podcast_script.py \
  --pack packs/demo-study-skills \
  --output podcast/script.txt \
  --model claude-sonnet-4-20250514
```

### What the AI Generates

A typical auto-generated script includes:

1. **Introduction** — Welcoming the listener, previewing topics
2. **Concept-by-concept review** — Each concept from the concept map gets covered
3. **Interactive Q&A** — The "student" voice asks questions, sometimes gives wrong answers
4. **Misconception corrections** — The "tutor" corrects common mistakes
5. **Mnemonics and exam tips** — Memory aids and test-taking strategies
6. **Quick-fire review** — Rapid concept checks near the end
7. **Closing** — Summary and encouragement

### Customizing the Prompt

You can influence the generated script by customizing your pack's `pack.yaml`:

```yaml
# The AI persona affects the tutor's voice/style
ai_persona: "You are a chemistry professor who loves real-world analogies.
  Always connect abstract concepts to everyday examples."
ai_persona_name: "Dr. Chem"

# Exam format info helps the AI focus on what's tested
exam_format:
  questions: 50
  time_minutes: 75
  question_types: ["multiple_choice", "calculation"]
```

---

## Voice Selection

### Default Voice Pair

The default voices are:

| Role | Voice ID | Description |
|------|----------|-------------|
| VOICE1 (Tutor) | `en-US-AndrewMultilingualNeural` | Male, clear, authoritative |
| VOICE2 (Student) | `en-US-EmmaMultilingualNeural` | Female, natural, conversational |

### Available English Voices

Edge-TTS provides many high-quality neural voices. Here are the best options for podcasts:

#### US English Voices

| Voice ID | Gender | Style | Good For |
|----------|--------|-------|----------|
| `en-US-AndrewMultilingualNeural` | Male | Warm, clear | Tutor / host |
| `en-US-EmmaMultilingualNeural` | Female | Natural, engaging | Student / co-host |
| `en-US-GuyNeural` | Male | Professional | Tutor / narrator |
| `en-US-JennyNeural` | Female | Friendly, clear | Student / co-host |
| `en-US-DavisNeural` | Male | Casual, warm | Casual tutor |
| `en-US-AriaNeural` | Female | Expressive | Engaged student |
| `en-US-TonyNeural` | Male | Deep, confident | Authority figure |
| `en-US-SaraNeural` | Female | Calm, clear | Steady narrator |

#### British English Voices

| Voice ID | Gender | Style | Good For |
|----------|--------|-------|----------|
| `en-GB-RyanNeural` | Male | British professional | Distinguished tutor |
| `en-GB-SoniaNeural` | Female | British clear | Articulate student |

#### Australian English Voices

| Voice ID | Gender | Style | Good For |
|----------|--------|-------|----------|
| `en-AU-WilliamNeural` | Male | Australian casual | Relaxed host |
| `en-AU-NatashaNeural` | Female | Australian friendly | Approachable co-host |

### Specifying Custom Voices

```bash
# Audio podcast with custom voices
python tools/generate_podcast.py \
  --script podcast/script.txt \
  --output podcast/review.mp3 \
  --voice1 "en-US-GuyNeural" \
  --voice2 "en-US-JennyNeural"

# Video podcast with custom voices
python tools/generate_podcast_video.py \
  --script podcast/script.txt \
  --output podcast/review_video.mp4 \
  --voice1 "en-GB-RyanNeural" \
  --voice2 "en-GB-SoniaNeural"
```

### Tips for Picking Good Voice Pairs

1. **Contrast is key.** Pick voices that are distinct from each other — different genders, or clearly different timbres. The listener needs to instantly know who's speaking.
2. **Match the subject tone.** Professional subjects → `GuyNeural` + `JennyNeural`. Casual study vibe → `DavisNeural` + `AriaNeural`.
3. **Avoid two similar voices.** Two male US voices or two female US voices can be hard to distinguish.
4. **Test with a short script first.** Generate a 30-second clip to verify the voices sound good together before committing to a full podcast.

### Listing All Available Voices

```bash
# List all available Edge-TTS voices
edge-tts --list-voices

# Filter for English voices
edge-tts --list-voices | grep "en-"

# Test a specific voice
edge-tts --voice "en-US-AndrewMultilingualNeural" --text "Hello, welcome to the review session." --write-media test.mp3
```

---

## Video Podcasts

### How Video Generation Works

Video podcasts combine the audio with synchronized visual frames rendered by matplotlib:

```
Script + Audio Segments
       │
       ▼
┌─────────────────────────────┐
│  For each dialogue segment: │
│  1. Render matplotlib frame │
│     - Speaker label         │
│     - Dialogue text         │
│     - Concept highlight     │
│     - Optional graph/chart  │
│  2. Measure audio duration  │
│  3. Map frame → duration    │
└─────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  ffmpeg assembly:           │
│  - Concat frames at         │
│    correct durations        │
│  - Overlay audio track      │
│  - Encode to H.264 MP4     │
└─────────────────────────────┘
       │
       ▼
   review_video.mp4
```

### Frame Rendering

Each dialogue segment gets its own video frame rendered by matplotlib:

```python
# What a frame looks like (simplified):
# ┌─────────────────────────────────────────┐
# │                                         │
# │           🎓 TUTOR                      │
# │                                         │
# │   "Spaced repetition distributes your   │
# │    study sessions over time with        │
# │    increasing intervals..."             │
# │                                         │
# │   ── Concept: Spaced Repetition ──      │
# │                                         │
# └─────────────────────────────────────────┘
```

Frame details:
- **Resolution**: 1920x1080 (Full HD) by default
- **Background**: Dark theme matching the Cram-It UI (`#0f0f1a`)
- **Speaker label**: Color-coded — purple for tutor, pink for student
- **Text**: Word-wrapped, white, centered
- **Concept tag**: Shown below the text when a new concept is introduced

### Graph Integration

For quantitative courses, video frames can include matplotlib charts:

```python
# The video generator detects when the script mentions
# specific concepts that have associated graph_specs,
# and renders an appropriate visualization in the frame.

# Example: A supply-demand curve for economics
# Example: A titration curve for chemistry
# Example: A normal distribution for statistics
```

### matplotlib Requirements

Video generation requires matplotlib's `Agg` backend (non-interactive, no display needed):

```python
import matplotlib
matplotlib.use('Agg')  # Must be set before importing pyplot
import matplotlib.pyplot as plt
```

This works on headless servers without any display/GUI packages.

### Usage

```bash
# Basic video generation
python tools/generate_podcast_video.py \
  --script podcast/script.txt \
  --output podcast/review_video.mp4

# Custom resolution
python tools/generate_podcast_video.py \
  --script podcast/script.txt \
  --output podcast/review_video.mp4 \
  --width 1280 --height 720

# Custom voices
python tools/generate_podcast_video.py \
  --script podcast/script.txt \
  --output podcast/review_video.mp4 \
  --voice1 "en-US-GuyNeural" \
  --voice2 "en-US-JennyNeural"

# Specify ffmpeg path (if not on PATH)
python tools/generate_podcast_video.py \
  --script podcast/script.txt \
  --output podcast/review_video.mp4 \
  --ffmpeg /opt/homebrew/bin/ffmpeg
```

---

## Integration with Cram-It PWA

### The Podcast Tab

The Cram-It PWA includes a dedicated **Pod** tab in the bottom navigation bar. When a user taps it, they see:

- 🎙️ **Podcast player** — Standard HTML5 audio player
- **Topics covered** — List of concepts reviewed in the podcast
- **Listening tip** — "Play on your commute, before bed, or while reviewing"

### File Serving

The Flask server serves podcast files from the `podcast/` directory:

```python
@app.route("/podcast/<path:fn>")
def serve_podcast(fn):
    return send_from_directory("podcast", fn)
```

### Expected File Locations

Place your generated files in the `podcast/` directory at the project root:

```
cram-it/
├── podcast/
│   ├── review.mp3          ← Audio podcast (loaded by default)
│   ├── review_video.mp4    ← Video podcast (optional)
│   └── script.txt          ← Source script (for reference)
├── server.py
├── packs/
└── ...
```

The PWA's audio player points to `/podcast/review.mp3` by default:

```html
<audio id="podcast-player" controls preload="metadata">
  <source id="podcast-source" src="/podcast/review.mp3" type="audio/mpeg">
</audio>
```

### Creating the Podcast Directory

The `podcast/` directory is not included in the repo by default. Create it before generating:

```bash
mkdir -p podcast
```

### Serving Video Podcasts

Video podcasts can be served at the same endpoint. To link the video in the PWA, you can update the podcast source or add a video element alongside the audio player. The default setup serves any file from `podcast/`:

```
GET /podcast/review.mp3        → Audio podcast
GET /podcast/review_video.mp4  → Video podcast
```

---

## Tips & Best Practices

### Script Writing

1. **Start with a hook.** The first 30 seconds should grab attention: "Did you know that most students use study techniques that actually hurt their performance?"

2. **One concept at a time.** Don't try to explain three things at once. Let the tutor finish one idea before the student asks about the next.

3. **Use the student voice for misconceptions.** Have VOICE2 say common wrong answers so the tutor can correct them. This is pedagogically powerful — students remember corrections better than plain explanations.

4. **Include mnemonics.** "Here's how I remember it: SN2 = Straight, No waiting — it's a one-step mechanism."

5. **Signal transitions.** "Alright, let's move on to our next topic: interleaving."

6. **End each concept with a check.** "Quick quiz: what are the three key factors that favor an SN2 mechanism?"

### Pacing

1. **Target 8–15 minutes.** Shorter podcasts get finished; longer ones get abandoned. For a pack with 6 concepts, ~10 minutes is ideal.

2. **2–3 minutes per concept.** Spend enough time to explain, give an example, and do a quick check — but don't belabor the point.

3. **Vary segment length.** Mix short punchy exchanges (1 sentence each) with longer explanations. This keeps the rhythm interesting.

4. **Pause at transitions.** The audio generator adds 500ms pauses between segments automatically, but you can add extra pauses by having both speakers do a brief transition line.

### Concept Coverage

1. **Cover prerequisites first.** Check your concept map's prerequisite chain and order topics accordingly.

2. **Hit high-frequency topics harder.** If your `exam_weights.json` shows that certain concepts appear on 40% of exams, dedicate more time to them.

3. **Don't skip "easy" concepts.** Even simple topics deserve a 30-second mention. Students often get overconfident on basics and make careless errors.

4. **Connect concepts.** "This relates to what we covered earlier about retrieval practice — interleaving is basically retrieval practice applied across topics."

### Audio Quality

1. **Avoid special characters.** Edge-TTS may read symbols literally. Write "percent" instead of "%", "plus" instead of "+".

2. **Spell out abbreviations** on first use. "SN2 — that's Substitution Nucleophilic Bimolecular" rather than just "SN2".

3. **Use natural language.** Write dialogue as people actually speak, not as textbook prose. "So basically, you're saying that..." is better than "In summary, the aforementioned..."

4. **Watch for homophones and confusable terms.** Edge-TTS usually handles context well, but test tricky terms.

---

## Troubleshooting

### ffmpeg Not Found

**Error:** `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`

**Cause:** ffmpeg is not installed or not on your PATH.

**Fix:**
```bash
# Install ffmpeg
brew install ffmpeg  # macOS
sudo apt install ffmpeg  # Ubuntu/Debian

# Or specify the full path
python tools/generate_podcast.py \
  --script podcast/script.txt \
  --output podcast/review.mp3 \
  --ffmpeg /opt/homebrew/bin/ffmpeg
```

### Edge-TTS Voice Errors

**Error:** `edge_tts.exceptions.NoAudioReceived` or voice name not recognized.

**Cause:** Invalid voice name, or Edge-TTS service temporarily unavailable.

**Fix:**
```bash
# Verify voice name is valid
edge-tts --list-voices | grep "AndrewMultilingual"

# Test the voice directly
edge-tts --voice "en-US-AndrewMultilingualNeural" \
  --text "Test" --write-media test.mp3

# If the service is down, wait a few minutes and retry.
# Edge-TTS uses Microsoft's free service which occasionally has outages.
```

### Anthropic API Key Missing

**Error:** `anthropic.AuthenticationError` or `ANTHROPIC_API_KEY not set`

**Cause:** The API key environment variable is not set.

**Fix:**
```bash
export ANTHROPIC_API_KEY="sk-ant-your-key-here"

# Or pass it inline
ANTHROPIC_API_KEY="sk-ant-..." python tools/generate_podcast_script.py \
  --pack packs/demo-study-skills \
  --output podcast/script.txt
```

### Empty or Very Short Audio

**Error:** Generated MP3 is 0 bytes or only a few seconds long.

**Cause:** Script parsing failed — likely no `[VOICE1]`/`[VOICE2]` tags found.

**Fix:** Check your script format:
```bash
# Verify tags exist
grep -c "\[VOICE1\]" podcast/script.txt
grep -c "\[VOICE2\]" podcast/script.txt

# Both should return non-zero counts
```

### matplotlib Backend Error

**Error:** `_tkinter.TclError: no display name and no $DISPLAY environment variable`

**Cause:** matplotlib is trying to use an interactive backend on a headless server.

**Fix:** The tools set `matplotlib.use('Agg')` automatically, but if you see this error, ensure the import order is correct:
```python
import matplotlib
matplotlib.use('Agg')  # MUST be before importing pyplot
import matplotlib.pyplot as plt
```

Or set the backend via environment variable:
```bash
MPLBACKEND=Agg python tools/generate_podcast_video.py ...
```

### Video Has No Audio

**Error:** MP4 file plays but is silent.

**Cause:** ffmpeg couldn't find or merge the audio track.

**Fix:** Ensure ffmpeg was compiled with AAC support:
```bash
ffmpeg -codecs | grep aac
# Should show: DEA.L. aac

# If missing, reinstall ffmpeg with full codecs
brew reinstall ffmpeg  # macOS
sudo apt install ffmpeg libavcodec-extra  # Ubuntu
```

### Podcast Tab Shows "Loading..."

**Error:** The Pod tab in the PWA shows "Loading topics from course pack..." indefinitely.

**Cause:** No podcast file exists at `podcast/review.mp3`.

**Fix:**
```bash
# Generate the podcast first
mkdir -p podcast
python tools/generate_podcast.py \
  --script podcast/script.txt \
  --output podcast/review.mp3

# Verify the file exists
ls -la podcast/review.mp3
```

### Script Generation Takes Too Long

**Cause:** Claude API latency or very large concept maps.

**Fix:**
- Use `claude-sonnet-4-20250514` instead of Opus for faster generation
- Reduce the number of sample questions passed to the prompt
- For very large packs (50+ concepts), consider generating multiple shorter podcasts by topic group

### Permission Denied Writing to podcast/

**Fix:**
```bash
mkdir -p podcast
chmod 755 podcast
```

---

## Full Walkthrough: Demo Study Skills Pack

This walkthrough generates a complete podcast for the built-in `demo-study-skills` course pack, which covers 6 study skill concepts: spaced repetition, retrieval practice, interleaving, elaboration, metacognition, and desirable difficulties.

### Step 0: Verify Prerequisites

```bash
# Check Python packages
python -c "import edge_tts; print('edge-tts:', edge_tts.__version__)" 2>/dev/null || echo "MISSING: pip install edge-tts"
python -c "import anthropic; print('anthropic: OK')" 2>/dev/null || echo "MISSING: pip install anthropic"
python -c "import matplotlib; print('matplotlib:', matplotlib.__version__)" 2>/dev/null || echo "MISSING: pip install matplotlib"
python -c "import pydub; print('pydub: OK')" 2>/dev/null || echo "MISSING: pip install pydub"

# Check ffmpeg
ffmpeg -version 2>/dev/null | head -1 || echo "MISSING: brew install ffmpeg"

# Check API key
[ -n "$ANTHROPIC_API_KEY" ] && echo "API key: set" || echo "MISSING: export ANTHROPIC_API_KEY=..."
```

### Step 1: Create the Podcast Directory

```bash
cd ~/Desktop/cram-it
mkdir -p podcast
```

### Step 2: Generate the Script

```bash
python tools/generate_podcast_script.py \
  --pack packs/demo-study-skills \
  --output podcast/script.txt \
  --duration 10
```

This reads the concept map (spaced repetition, retrieval practice, interleaving, elaboration, metacognition, desirable difficulties) and the 10 questions from the question bank, then generates a ~10-minute dialogue.

**Expected output:**
```
Loading pack: packs/demo-study-skills
  Concepts: 6
  Questions: 10
Generating script with Claude...
Script generated: 47 dialogue segments
Written to: podcast/script.txt
```

### Step 3: Review the Script (Optional)

Open `podcast/script.txt` and scan for:
- All 6 concepts are covered
- The dialogue sounds natural
- No garbled text or formatting issues

You can edit the script manually before generating audio. For example, you might add a mnemonic or fix an awkward phrase.

### Step 4: Generate the Audio Podcast

```bash
python tools/generate_podcast.py \
  --script podcast/script.txt \
  --output podcast/review.mp3 \
  --voice1 "en-US-AndrewMultilingualNeural" \
  --voice2 "en-US-EmmaMultilingualNeural"
```

**Expected output:**
```
Parsing script: 47 segments
Generating audio segments...
  [1/47] VOICE1: "Welcome to today's review..." (2.3s)
  [2/47] VOICE2: "Thanks! I'm really looking..." (1.8s)
  ...
  [47/47] VOICE1: "Great session today..." (2.1s)
Concatenating segments with 500ms pauses...
Final podcast: 9:42 duration
Written to: podcast/review.mp3
```

### Step 5: Generate the Video Podcast (Optional)

```bash
python tools/generate_podcast_video.py \
  --script podcast/script.txt \
  --output podcast/review_video.mp4 \
  --voice1 "en-US-AndrewMultilingualNeural" \
  --voice2 "en-US-EmmaMultilingualNeural"
```

**Expected output:**
```
Parsing script: 47 segments
Generating audio segments...
Rendering video frames...
  [1/47] Frame: VOICE1 - "Welcome to today's review..."
  [2/47] Frame: VOICE2 - "Thanks! I'm really looking..."
  ...
Assembling video with ffmpeg...
Final video: 9:42 duration, 1920x1080
Written to: podcast/review_video.mp4
```

### Step 6: Start the Server and Listen

```bash
python server.py
```

Open `http://localhost:3000` in your browser. Tap the **Pod** tab (microphone icon) in the bottom navigation bar. You should see:

- 🎙️ **Cram-It: Audio Review**
- An audio player with play/pause controls
- **Topics Covered:** Spaced Repetition, Retrieval Practice, Interleaving, Elaboration, Metacognition, Desirable Difficulties
- A tip: "Play on your commute, before bed, or while reviewing."

Press play and enjoy your AI-generated study review podcast!

### What the Demo Podcast Covers

For the Study Skills 101 pack, the generated podcast typically includes:

1. **Introduction** (~30s) — Welcome, preview of topics
2. **Spaced Repetition** (~2 min) — Spacing effect, optimal intervals, comparison to cramming
3. **Retrieval Practice** (~2 min) — Testing effect, flashcards vs. re-reading, self-quizzing techniques
4. **Interleaving** (~1.5 min) — Mixed practice vs. blocked practice, when to interleave
5. **Elaboration** (~1.5 min) — Generating explanations, connecting to prior knowledge
6. **Metacognition** (~1.5 min) — Self-monitoring, calibration, the Dunning-Kruger effect
7. **Desirable Difficulties** (~1 min) — Why harder practice leads to better learning
8. **Quick Review** (~1 min) — Rapid-fire concept checks
9. **Closing** (~30s) — Summary and encouragement

---

## Further Reading

- [Podcast Generation Skill](./skills/podcast-generation.md) — Technical architecture and code details
- [Creating Packs](./CREATING_PACKS.md) — How to create course packs that feed into podcast generation
- [Architecture](./ARCHITECTURE.md) — Overall Cram-It system design
- [Edge-TTS Documentation](https://github.com/rany2/edge-tts) — Full Edge-TTS library reference
- [ffmpeg Documentation](https://ffmpeg.org/documentation.html) — ffmpeg command reference
