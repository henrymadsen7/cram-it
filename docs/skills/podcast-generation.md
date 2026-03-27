# Skill: Podcast Generation

> **User-facing guide:** For a comprehensive how-to guide with quick start, voice selection, examples, and troubleshooting, see **[PODCAST_GUIDE.md](../PODCAST_GUIDE.md)**.

## Overview

Cram-It can generate audio and video review podcasts using Edge-TTS for voice synthesis and matplotlib + ffmpeg for video rendering. The output is a two-voice dialogue format — like a study session between a tutor and a student.

## CLI Tools

Three command-line tools implement the full pipeline:

| Tool | Purpose |
|------|---------|
| `tools/generate_podcast_script.py` | AI script generation from pack content (requires Anthropic API key) |
| `tools/generate_podcast.py` | Converts a `[VOICE1]`/`[VOICE2]` script into an MP3 audio podcast via Edge-TTS |
| `tools/generate_podcast_video.py` | Converts a script into an MP4 video podcast with matplotlib-rendered frames + Edge-TTS audio |

### Quick Start

```bash
# 1. Generate script from course pack
python tools/generate_podcast_script.py --pack packs/demo-study-skills --output podcast/script.txt

# 2. Generate audio podcast
python tools/generate_podcast.py --script podcast/script.txt --output podcast/review.mp3

# 3. (Optional) Generate video podcast
python tools/generate_podcast_video.py --script podcast/script.txt --output podcast/review_video.mp4
```

See [PODCAST_GUIDE.md](../PODCAST_GUIDE.md) for full documentation including voice selection, custom scripts, troubleshooting, and a complete walkthrough.

### Minimum Content Gate

All three tools enforce a minimum content threshold before running:
- **10+ questions** in `questions.json`
- **3+ concepts** in `concept_map.json`

This prevents generating shallow, useless podcasts from nearly-empty packs. Override with `--force` if needed.

---

## Architecture

```
Concept Map + Questions → Claude (script generation) → Edge-TTS (audio)
                                                          ↓
                                                    matplotlib (frames)
                                                          ↓
                                                    ffmpeg (video)
                                                          ↓
                                                    podcast/*.mp4
```

---

## Edge-TTS Pipeline

### What is Edge-TTS?

Edge-TTS is Microsoft's text-to-speech service, accessed via the `edge-tts` Python library. It's free, high-quality, and supports multiple voices.

### Voice Selection

Two voices are used for the dialogue:

```python
import edge_tts

VOICE_TUTOR = "en-US-GuyNeural"      # Male tutor voice
VOICE_STUDENT = "en-US-JennyNeural"  # Female student voice
```

### Generating Audio Segments

Each dialogue line is converted to an audio file:

```python
async def generate_audio_segment(text, voice, output_path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)
```

### Concatenating Audio

Individual segments are concatenated with short pauses:

```python
from pydub import AudioSegment

def concatenate_segments(segment_paths, output_path, pause_ms=500):
    combined = AudioSegment.empty()
    pause = AudioSegment.silent(duration=pause_ms)

    for path in segment_paths:
        segment = AudioSegment.from_file(path)
        combined += segment + pause

    combined.export(output_path, format="mp3")
```

---

## Two-Voice Dialogue Format

### Script Generation

Claude generates a study dialogue from the concept map and question bank:

```python
prompt = f"""Generate a 10-minute study review podcast script.
Format: A dialogue between a tutor and a student reviewing for an exam.

Topics to cover:
{concept_list}

Key questions from the exam bank:
{question_samples}

Rules:
- Tutor explains concepts clearly and concisely
- Student asks clarifying questions and sometimes gives wrong answers
- Tutor corrects misconceptions
- Include mnemonics and exam tips
- Cover calculation steps for quantitative concepts
- End each topic with a quick-fire question

Format each line as:
TUTOR: [dialogue text]
STUDENT: [dialogue text]
"""
```

### Script Parsing

```python
def parse_script(script_text):
    lines = []
    for line in script_text.strip().split('\n'):
        if line.startswith('TUTOR:'):
            lines.append({
                'speaker': 'tutor',
                'text': line[6:].strip(),
                'voice': VOICE_TUTOR,
            })
        elif line.startswith('STUDENT:'):
            lines.append({
                'speaker': 'student',
                'text': line[8:].strip(),
                'voice': VOICE_STUDENT,
            })
    return lines
```

---

## Video Generation

### Frame Rendering with matplotlib

Each dialogue line gets a video frame showing the current text and speaker:

```python
import matplotlib.pyplot as plt
import matplotlib

matplotlib.use('Agg')  # Non-interactive backend

def render_frame(text, speaker, frame_path, dimensions=(1920, 1080)):
    fig, ax = plt.subplots(figsize=(dimensions[0]/100, dimensions[1]/100), dpi=100)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    # Background
    fig.patch.set_facecolor('#0f0f1a')

    # Speaker indicator
    color = '#818cf8' if speaker == 'tutor' else '#f472b6'
    label = 'TUTOR' if speaker == 'tutor' else 'STUDENT'
    ax.text(0.5, 0.75, label, ha='center', va='center',
            fontsize=24, color=color, fontweight='bold')

    # Dialogue text (word-wrapped)
    ax.text(0.5, 0.45, text, ha='center', va='center',
            fontsize=18, color='white', wrap=True,
            fontfamily='sans-serif')

    plt.savefig(frame_path, facecolor=fig.get_facecolor(),
                bbox_inches='tight', pad_inches=0.5)
    plt.close()
```

### Video Assembly with ffmpeg

```python
import subprocess

def create_video(frames_with_durations, audio_path, output_path):
    # Create a concat file for ffmpeg
    concat_file = 'frames_concat.txt'
    with open(concat_file, 'w') as f:
        for frame_path, duration in frames_with_durations:
            f.write(f"file '{frame_path}'\n")
            f.write(f"duration {duration}\n")

    # Generate video from frames
    subprocess.run([
        'ffmpeg', '-f', 'concat', '-safe', '0',
        '-i', concat_file,
        '-i', audio_path,
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac',
        '-shortest',
        output_path
    ])
```

---

## Full Pipeline

### Step-by-Step

1. **Generate Script**: Claude creates a two-voice dialogue from pack content
2. **Parse Script**: Split into individual speaker lines
3. **Generate Audio**: Edge-TTS creates audio for each line
4. **Render Frames**: matplotlib creates a frame image for each line
5. **Measure Durations**: Get audio duration for each segment
6. **Assemble Video**: ffmpeg combines frames + audio
7. **Serve**: Flask serves from `podcast/` directory

### Usage

```python
async def generate_podcast(pack_name, output_dir="podcast"):
    # 1. Load pack content
    concepts = load_concept_map(pack_name)
    questions = load_question_samples(pack_name)

    # 2. Generate script with Claude
    script = generate_podcast_script(concepts, questions)
    lines = parse_script(script)

    # 3. Generate audio segments
    audio_segments = []
    for i, line in enumerate(lines):
        audio_path = f"{output_dir}/segment_{i:03d}.mp3"
        await generate_audio_segment(line['text'], line['voice'], audio_path)
        audio_segments.append(audio_path)

    # 4. Concatenate audio
    full_audio = f"{output_dir}/full_audio.mp3"
    concatenate_segments(audio_segments, full_audio)

    # 5. Render frames
    frames = []
    for i, line in enumerate(lines):
        frame_path = f"{output_dir}/frame_{i:03d}.png"
        render_frame(line['text'], line['speaker'], frame_path)
        duration = get_audio_duration(audio_segments[i])
        frames.append((frame_path, duration))

    # 6. Create video
    video_path = f"{output_dir}/review_podcast.mp4"
    create_video(frames, full_audio, video_path)

    return video_path
```

### Serving Podcasts

The Flask server serves podcast files:

```python
@app.route("/podcast/<path:fn>")
def serve_podcast(fn):
    return send_from_directory("podcast", fn)
```

---

## Customization

### Different Voice Pairs

```python
# British voices
VOICE_TUTOR = "en-GB-RyanNeural"
VOICE_STUDENT = "en-GB-SoniaNeural"

# More casual
VOICE_TUTOR = "en-US-DavisNeural"
VOICE_STUDENT = "en-US-AriaNeural"
```

### Script Styles

- **Review mode**: Systematic topic-by-topic review
- **Q&A mode**: Student asks questions, tutor answers
- **Quiz mode**: Tutor quizzes student, corrects mistakes
- **Story mode**: Concepts woven into a narrative

### Video Styles

- **Text only**: Current implementation
- **With diagrams**: Include graph renders in frames
- **Slide-style**: Use lecture slides as backgrounds
- **Animated**: matplotlib animations for graph transitions

---

## Dependencies

```
edge-tts>=6.1        # Voice synthesis
pydub>=0.25          # Audio manipulation
matplotlib>=3.7      # Frame rendering
Pillow>=10.0         # Image handling
# System: ffmpeg must be installed
```

### Installing ffmpeg

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```
