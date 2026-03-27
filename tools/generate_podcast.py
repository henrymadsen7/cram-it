#!/usr/bin/env python3
"""
Generate Two-Voice Podcast from Script using Edge-TTS

Takes a pre-written script (with [VOICE1]/[VOICE2] markers) and generates
a two-voice podcast MP3 using Microsoft Edge TTS (free, no API key needed).

If no script is provided, auto-generates one from the pack's content using
the generate_podcast_script module.

Requirements:
  pip install edge-tts
  ffmpeg (system install)

Usage:
  # From a pre-written script:
  python tools/generate_podcast.py --script path/to/script.txt --output podcast.mp3

  # Auto-generate from a course pack:
  python tools/generate_podcast.py --pack-dir packs/my-course --output podcast.mp3

  # Custom voices:
  python tools/generate_podcast.py --script script.txt --output podcast.mp3 \
      --voice1 en-US-GuyNeural --voice2 en-US-JennyNeural

  # With custom speech rate:
  python tools/generate_podcast.py --script script.txt --output podcast.mp3 --rate "+10%"
"""
import subprocess
import re
import os
import sys
import shutil
import tempfile
import argparse
from pathlib import Path


# Default voices (Microsoft Edge TTS - free, no API key)
DEFAULT_VOICE1 = "en-US-AndrewMultilingualNeural"   # Host
DEFAULT_VOICE2 = "en-US-EmmaMultilingualNeural"      # Expert


def find_ffmpeg():
    """Find ffmpeg binary on the system."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    # Common paths
    for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        "ffmpeg not found. Install it: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
    )


def find_ffprobe():
    """Find ffprobe binary on the system."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        return ffprobe
    for p in ["/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe", "/usr/bin/ffprobe"]:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("ffprobe not found. Install ffmpeg package.")


def parse_script(path):
    """
    Parse a podcast script with [VOICE1]/[VOICE2] speaker markers.

    Expected format:
      [VOICE1] Hello and welcome to the show!
      [VOICE2] Thanks for having me.
      # Comments and blank lines are ignored

    Returns list of (speaker_key, text) tuples.
    Speaker keys are 'VOICE1' and 'VOICE2'.
    """
    segments = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'\[(VOICE[12])\]\s*(.*)', line)
            if m:
                speaker = m.group(1)
                text = m.group(2).strip()
                if text:
                    segments.append((speaker, text))
    return segments


def generate_segment(idx, speaker, text, voice, rate, work_dir):
    """Generate a single TTS audio segment using edge-tts."""
    outfile = os.path.join(work_dir, f"seg_{idx:03d}_{speaker.lower()}.mp3")
    cmd = [
        sys.executable, "-m", "edge_tts",
        "--voice", voice,
        "--rate", rate,
        "--text", text,
        "--write-media", outfile,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"  ERROR seg {idx}: {result.stderr[:200]}")
        return None
    return outfile


def concat_segments(segment_files, output_path, ffmpeg, work_dir):
    """Concatenate all segment MP3s into final output file."""
    concat_file = os.path.join(work_dir, "concat.txt")
    with open(concat_file, "w") as f:
        for sf in segment_files:
            f.write(f"file '{sf}'\n")

    cmd = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"FFMPEG ERROR: {result.stderr[:500]}")
        return None
    return output_path


def get_audio_info(filepath, ffprobe):
    """Get duration and size of an audio file."""
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration", "-of", "csv=p=0", filepath],
        capture_output=True, text=True
    )
    duration = float(probe.stdout.strip())
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    return duration, size_mb


def generate_podcast(script_path, output_path, voice1=None, voice2=None, rate="+12%"):
    """
    Main podcast generation pipeline.

    Args:
        script_path: Path to the script file with [VOICE1]/[VOICE2] markers
        output_path: Path for the output MP3 file
        voice1: Edge TTS voice name for VOICE1 (Host)
        voice2: Edge TTS voice name for VOICE2 (Expert)
        rate: Speech rate adjustment (e.g., "+12%", "-5%", "+0%")

    Returns:
        Path to the generated MP3, or None on failure
    """
    voice1 = voice1 or DEFAULT_VOICE1
    voice2 = voice2 or DEFAULT_VOICE2
    voices = {"VOICE1": voice1, "VOICE2": voice2}

    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()

    # Parse the script
    segments = parse_script(script_path)
    print(f"Parsed {len(segments)} segments from {script_path}")
    if not segments:
        print("ERROR: No segments found in script. Expected [VOICE1] or [VOICE2] markers.")
        return None

    # Create temp working directory for intermediate files
    work_dir = tempfile.mkdtemp(prefix="podcast_")
    try:
        # Generate individual TTS segments
        segment_files = []
        for i, (speaker, text) in enumerate(segments):
            voice = voices.get(speaker, voice1)
            print(f"  Generating seg {i:03d} [{speaker}] ({len(text)} chars)...")
            outfile = generate_segment(i, speaker, text, voice, rate, work_dir)
            if outfile:
                segment_files.append(outfile)
            else:
                print(f"  FAILED seg {i}, skipping")

        if not segment_files:
            print("ERROR: No segments were generated successfully.")
            return None

        # Ensure output directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # Concatenate into final MP3
        print(f"\nConcatenating {len(segment_files)} segments...")
        final = concat_segments(segment_files, output_path, ffmpeg, work_dir)

        if final:
            duration, size_mb = get_audio_info(final, ffprobe)
            mins = int(duration // 60)
            secs = int(duration % 60)
            print(f"\nDONE: {final}")
            print(f"Duration: {mins}m {secs}s")
            print(f"Size: {size_mb:.1f} MB")
            return final
        else:
            print("FAILED to create final file")
            return None

    finally:
        # Clean up temp directory
        shutil.rmtree(work_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a two-voice podcast MP3 from a script using Edge TTS",
        epilog="Requires: pip install edge-tts; ffmpeg installed on system"
    )
    parser.add_argument("--script", type=str, default=None,
                        help="Path to podcast script with [VOICE1]/[VOICE2] markers")
    parser.add_argument("--pack-dir", type=str, default=None,
                        help="Path to course pack directory (auto-generates script if --script not given)")
    parser.add_argument("--output", "-o", type=str, default="podcast.mp3",
                        help="Output MP3 file path (default: podcast.mp3)")
    parser.add_argument("--voice1", type=str, default=DEFAULT_VOICE1,
                        help=f"Edge TTS voice for Host (default: {DEFAULT_VOICE1})")
    parser.add_argument("--voice2", type=str, default=DEFAULT_VOICE2,
                        help=f"Edge TTS voice for Expert (default: {DEFAULT_VOICE2})")
    parser.add_argument("--rate", type=str, default="+12%",
                        help="Speech rate adjustment (default: +12%%)")
    parser.add_argument("--topic", type=str, default=None,
                        help="Focus topic (passed to script generator if auto-generating)")

    args = parser.parse_args()

    if not args.script and not args.pack_dir:
        parser.error("Either --script or --pack-dir is required")

    script_path = args.script

    # Auto-generate script from pack if no script provided
    if not script_path:
        print("No script provided, auto-generating from pack content...")
        from generate_podcast_script import generate_script
        script_path = os.path.join(args.pack_dir, "podcast_script.txt")
        result = generate_script(
            pack_dir=args.pack_dir,
            output_path=script_path,
            topic=args.topic
        )
        if not result:
            print("ERROR: Failed to generate script")
            sys.exit(1)
        print(f"Script generated: {script_path}\n")

    result = generate_podcast(
        script_path=script_path,
        output_path=args.output,
        voice1=args.voice1,
        voice2=args.voice2,
        rate=args.rate,
    )

    if not result:
        sys.exit(1)


if __name__ == "__main__":
    main()
