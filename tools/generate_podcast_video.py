#!/usr/bin/env python3
"""
Generate Video Podcast from Audio + Auto-Generated Graphs

Takes a podcast audio file and a course pack, generates relevant concept
visualization graphs using matplotlib, then composites them into a video
podcast with ffmpeg.

The system:
1. Parses the script to identify topic segments
2. Auto-generates concept graphs based on pack content
3. Maps graphs to audio timestamps
4. Builds a video with synchronized visuals

Requirements:
  pip install matplotlib numpy pyyaml
  ffmpeg (system install)

Usage:
  # Full pipeline (audio + pack -> video):
  python tools/generate_podcast_video.py --audio podcast.mp3 --pack-dir packs/my-course

  # With explicit script for better segment mapping:
  python tools/generate_podcast_video.py --audio podcast.mp3 --pack-dir packs/my-course \
      --script podcast_script.txt

  # Custom output:
  python tools/generate_podcast_video.py --audio podcast.mp3 --pack-dir packs/my-course \
      -o podcast_video.mp4
"""
import subprocess
import os
import sys
import re
import json
import shutil
import tempfile
import argparse
import yaml
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np


# ─────────────────────────────────────────────
# Visual theme (dark mode, good for video)
# ─────────────────────────────────────────────
BG_COLOR = '#1a1a2e'
TEXT_COLOR = '#e0e0e0'
GRID_COLOR = '#2a2a4a'
COLORS = {
    'cyan':   '#00d4ff',   # primary / demand
    'red':    '#ff6b6b',   # MC / warnings
    'yellow': '#ffd93d',   # ATC / highlights
    'green':  '#6bcb77',   # MR / profit / success
    'orange': '#ff8c42',   # AVC / secondary
    'purple': '#c084fc',   # annotations
}


def find_ffmpeg():
    """Find ffmpeg binary."""
    for candidate in [shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg",
                      "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if candidate and os.path.exists(candidate):
            return candidate
    raise FileNotFoundError("ffmpeg not found")


def find_ffprobe():
    """Find ffprobe binary."""
    for candidate in [shutil.which("ffprobe"), "/opt/homebrew/bin/ffprobe",
                      "/usr/local/bin/ffprobe", "/usr/bin/ffprobe"]:
        if candidate and os.path.exists(candidate):
            return candidate
    raise FileNotFoundError("ffprobe not found")


# ─────────────────────────────────────────────
# Graph Generation Utilities
# ─────────────────────────────────────────────
def style_ax(ax, title, xlabel='Quantity', ylabel='Price / Cost ($)'):
    """Apply consistent dark theme styling to a matplotlib axis."""
    ax.set_facecolor(BG_COLOR)
    ax.set_title(title, color=TEXT_COLOR, fontsize=20, fontweight='bold', pad=15)
    ax.set_xlabel(xlabel, color=TEXT_COLOR, fontsize=14)
    ax.set_ylabel(ylabel, color=TEXT_COLOR, fontsize=14)
    ax.tick_params(colors=TEXT_COLOR, labelsize=11)
    for spine in ax.spines.values():
        spine.set_color('#444466')
    ax.grid(True, alpha=0.15, color=GRID_COLOR)


def fig_setup(figsize=(14, 9)):
    """Create a figure with dark background."""
    return plt.figure(figsize=figsize, facecolor=BG_COLOR)


def generate_title_card(outdir, course_name, subtitle="", topics=None):
    """
    Generate a title card image for the podcast.

    Args:
        outdir: Output directory for the image
        course_name: Course name to display
        subtitle: Optional subtitle
        topics: Optional list of topic strings
    """
    fig = fig_setup()
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG_COLOR)
    ax.axis('off')

    ax.text(0.5, 0.65, 'CRAM-IT', color=COLORS['cyan'], fontsize=52, fontweight='bold',
            ha='center', va='center', transform=ax.transAxes, family='monospace')

    if subtitle:
        ax.text(0.5, 0.48, subtitle, color=COLORS['purple'], fontsize=24,
                ha='center', va='center', transform=ax.transAxes)

    ax.text(0.5, 0.35, course_name, color=TEXT_COLOR, fontsize=18,
            ha='center', va='center', transform=ax.transAxes)

    if topics:
        topics_str = '  \u2022  '.join(topics[:6])  # bullet-separated, max 6
        ax.text(0.5, 0.22, topics_str, color=COLORS['yellow'], fontsize=14,
                ha='center', va='center', transform=ax.transAxes)

    path = os.path.join(outdir, 'title_card.png')
    fig.savefig(path, dpi=150, facecolor=BG_COLOR, bbox_inches='tight')
    plt.close()
    return path


def generate_concept_card(outdir, concept_name, description="", key_points=None, index=0):
    """
    Generate a concept visualization card.

    Args:
        outdir: Output directory
        concept_name: Name of the concept
        description: Brief description
        key_points: List of key points/rules
        index: Numeric index for filename ordering
    """
    fig = fig_setup()
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG_COLOR)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    # Concept title
    ax.text(5, 8.5, concept_name.upper(), color=COLORS['cyan'], fontsize=28,
            fontweight='bold', ha='center')

    # Description
    if description:
        ax.text(5, 7.2, description, color=TEXT_COLOR, fontsize=16,
                ha='center', wrap=True)

    # Key points box
    if key_points:
        points_text = "\n".join(f"\u2022 {p}" for p in key_points[:8])
        box = patches.FancyBboxPatch((1, 1.5), 8, 5, boxstyle='round,pad=0.4',
                                      facecolor='#2a2a4a', edgecolor=COLORS['purple'],
                                      linewidth=2)
        ax.add_patch(box)
        ax.text(5, 4, points_text, color=TEXT_COLOR, fontsize=14,
                ha='center', va='center', family='monospace',
                linespacing=1.8)

    path = os.path.join(outdir, f'concept_{index:02d}_{_slugify(concept_name)}.png')
    fig.savefig(path, dpi=150, facecolor=BG_COLOR, bbox_inches='tight')
    plt.close()
    return path


def generate_formula_card(outdir, title, formulas, examples=None, index=0):
    """
    Generate a formula/equation visualization card.

    Args:
        outdir: Output directory
        title: Card title
        formulas: List of formula strings
        examples: Optional list of example strings
        index: Numeric index for filename ordering
    """
    fig = fig_setup()
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG_COLOR)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    ax.set_title(title.upper(), color=TEXT_COLOR, fontsize=22, fontweight='bold', pad=20)

    # Formulas
    y_pos = 7.5
    for formula in formulas[:5]:
        box = patches.FancyBboxPatch((0.5, y_pos - 0.6), 9, 1.2, boxstyle='round,pad=0.3',
                                      facecolor='#2a2a4a', edgecolor=COLORS['cyan'], linewidth=2)
        ax.add_patch(box)
        ax.text(5, y_pos, formula, color=TEXT_COLOR, fontsize=16,
                fontweight='bold', ha='center', va='center', family='monospace')
        y_pos -= 2.0

    # Examples
    if examples:
        y_pos -= 0.5
        for ex in examples[:3]:
            ax.text(5, y_pos, ex, color=COLORS['green'], fontsize=13, ha='center')
            y_pos -= 0.8

    path = os.path.join(outdir, f'formula_{index:02d}_{_slugify(title)}.png')
    fig.savefig(path, dpi=150, facecolor=BG_COLOR, bbox_inches='tight')
    plt.close()
    return path


def _slugify(text):
    """Convert text to a filesystem-safe slug."""
    return re.sub(r'[^a-z0-9]+', '_', text.lower().strip())[:40].strip('_')


# ─────────────────────────────────────────────
# Auto-generate graphs from pack content
# ─────────────────────────────────────────────
def generate_graphs_from_pack(pack_dir, graph_dir):
    """
    Auto-generate visualization graphs from pack content.

    Reads concept_map and knowledge_graph to create relevant visuals.
    Returns dict mapping concept_id -> image_path.
    """
    pack_path = Path(pack_dir)
    os.makedirs(graph_dir, exist_ok=True)
    graph_map = {}

    # Load pack config
    with open(pack_path / "pack.yaml") as f:
        config = yaml.safe_load(f)

    course_name = config.get("name", "Course Review")

    # Load concept map
    concept_map = {}
    cm_path = pack_path / "concept_map.json"
    if cm_path.exists():
        with open(cm_path) as f:
            concept_map = json.load(f)

    # Load knowledge graph
    knowledge_graph = {}
    kg_path = pack_path / "knowledge_graph.json"
    if kg_path.exists():
        with open(kg_path) as f:
            knowledge_graph = json.load(f)

    # Generate title card
    topics = []
    if concept_map:
        for cid, info in list(concept_map.items())[:6]:
            if isinstance(info, dict):
                topics.append(info.get("name", cid))
            else:
                topics.append(str(cid))

    title_path = generate_title_card(graph_dir, course_name, "Study Review Podcast", topics)
    graph_map["_title"] = title_path
    print(f"  Generated: title card")

    # Generate concept cards
    for idx, (cid, info) in enumerate(concept_map.items()):
        if isinstance(info, dict):
            name = info.get("name", cid)
            desc = info.get("description", "")
            keywords = info.get("keywords", [])

            # Build key points from knowledge graph if available
            key_points = []
            kg_node = knowledge_graph.get(cid, {})
            if isinstance(kg_node, dict):
                if kg_node.get("equations"):
                    key_points.extend(kg_node["equations"][:3])
                if kg_node.get("misconceptions"):
                    key_points.extend([f"Common mistake: {m}" for m in kg_node["misconceptions"][:2]])
                if kg_node.get("key_facts"):
                    key_points.extend(kg_node["key_facts"][:3])
            if keywords and not key_points:
                key_points = [f"Key term: {kw}" for kw in keywords[:5]]

            path = generate_concept_card(graph_dir, name, desc, key_points, idx)
            graph_map[cid] = path
            print(f"  Generated: {name}")

        if idx >= 20:  # Limit to 20 concept cards
            break

    print(f"\nGenerated {len(graph_map)} graph images in {graph_dir}")
    return graph_map


# ─────────────────────────────────────────────
# Script Parsing & Timestamp Mapping
# ─────────────────────────────────────────────
def parse_script_segments(script_path):
    """Parse script into segments for timestamp mapping."""
    segments = []
    with open(script_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'\[(VOICE[12])\]\s*(.*)', line)
            if m:
                speaker = m.group(1)
                text = m.group(2).strip()
                if text:
                    segments.append({"speaker": speaker, "text": text})
    return segments


def get_duration(filepath, ffprobe):
    """Get duration of an audio/video file in seconds."""
    cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration",
           "-of", "csv=p=0", filepath]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def assign_graphs_to_segments(segments, graph_map, concept_map):
    """
    Assign graph images to script segments based on content keywords.

    Uses keyword matching between segment text and concept keywords
    to determine which visual to show.
    """
    # Build keyword -> concept_id mapping
    keyword_to_concept = {}
    for cid, info in concept_map.items():
        if isinstance(info, dict):
            name = info.get("name", cid).lower()
            keywords = [kw.lower() for kw in info.get("keywords", [])]
            keywords.append(name)
            keywords.append(cid.lower().replace("_", " "))
            for kw in keywords:
                keyword_to_concept[kw] = cid

    title_image = graph_map.get("_title", list(graph_map.values())[0] if graph_map else None)

    assignments = []
    for i, seg in enumerate(segments):
        text_lower = seg["text"].lower()

        # Find best matching concept
        best_match = None
        best_len = 0
        for kw, cid in keyword_to_concept.items():
            if kw in text_lower and len(kw) > best_len and cid in graph_map:
                best_match = cid
                best_len = len(kw)

        if best_match:
            image = graph_map[best_match]
        elif i <= 1 or i >= len(segments) - 2:
            # Intro/outro -> title card
            image = title_image
        else:
            image = title_image  # fallback

        assignments.append({
            "idx": i,
            "speaker": seg["speaker"],
            "text": seg["text"][:80],
            "concept": best_match or "_title",
            "image": image,
        })

    return assignments


def consolidate_ranges(assignments):
    """Merge consecutive segments with the same image into single ranges."""
    if not assignments:
        return []

    ranges = []
    current = None

    for a in assignments:
        if current is None or current["image"] != a["image"]:
            if current is not None:
                ranges.append(current)
            current = {
                "concept": a["concept"],
                "image": a["image"],
                "start_idx": a["idx"],
                "end_idx": a["idx"],
            }
        else:
            current["end_idx"] = a["idx"]

    if current:
        ranges.append(current)

    return ranges


# ─────────────────────────────────────────────
# Video Building
# ─────────────────────────────────────────────
def build_video(audio_path, ranges, segment_durations, output_path, ffmpeg, work_dir):
    """
    Build video by compositing graph images with the podcast audio.

    Creates individual image clips with durations matching their audio segments,
    concatenates them, then merges with the audio track.
    """
    # Calculate time ranges from segment durations
    cumulative = 0.0
    seg_starts = []
    for d in segment_durations:
        seg_starts.append(cumulative)
        cumulative += d

    temp_clips = []
    for i, r in enumerate(ranges):
        # Calculate duration for this range
        start_time = seg_starts[r["start_idx"]] if r["start_idx"] < len(seg_starts) else 0
        end_idx = min(r["end_idx"], len(seg_starts) - 1)
        end_time = seg_starts[end_idx] + segment_durations[end_idx] if end_idx < len(segment_durations) else cumulative
        duration = max(end_time - start_time, 0.5)

        clip_path = os.path.join(work_dir, f"clip_{i:03d}.mp4")

        if not r["image"] or not os.path.exists(r["image"]):
            print(f"  WARNING: Missing image for {r['concept']}, skipping")
            continue

        cmd = [
            ffmpeg, "-y",
            "-loop", "1",
            "-i", r["image"],
            "-t", f"{duration:.3f}",
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                   "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#1a1a2e",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", "24",
            clip_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  ERROR clip {i}: {result.stderr[:200]}")
            continue
        temp_clips.append(clip_path)
        print(f"  Clip {i}: {r['concept']} ({duration:.1f}s)")

    if not temp_clips:
        print("ERROR: No video clips generated")
        return None

    # Concat all clips
    concat_video = os.path.join(work_dir, "video_only.mp4")
    concat_list = os.path.join(work_dir, "clips.txt")
    with open(concat_list, "w") as f:
        for c in temp_clips:
            f.write(f"file '{c}'\n")

    cmd = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_list,
        "-c", "copy",
        concat_video,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"CONCAT ERROR: {result.stderr[:500]}")
        return None

    # Merge video + audio
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-i", concat_video,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"MERGE ERROR: {result.stderr[:500]}")
        return None

    return output_path


def generate_podcast_video(audio_path, pack_dir, output_path, script_path=None):
    """
    Main video podcast generation pipeline.

    Args:
        audio_path: Path to the podcast audio file (MP3)
        pack_dir: Path to the course pack directory
        output_path: Output video file path (MP4)
        script_path: Optional script file for better segment mapping

    Returns:
        Path to the generated video, or None on failure
    """
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    pack_path = Path(pack_dir)

    print("=== Building Video Podcast ===\n")

    # Load concept map
    concept_map = {}
    cm_path = pack_path / "concept_map.json"
    if cm_path.exists():
        with open(cm_path) as f:
            concept_map = json.load(f)

    # Step 1: Generate graphs
    work_dir = tempfile.mkdtemp(prefix="podcast_video_")
    graph_dir = os.path.join(work_dir, "graphs")

    print("Generating concept graphs...")
    graph_map = generate_graphs_from_pack(pack_dir, graph_dir)

    if not graph_map:
        # Create at least a title card
        with open(pack_path / "pack.yaml") as f:
            config = yaml.safe_load(f)
        title_path = generate_title_card(graph_dir, config.get("name", "Course Review"))
        graph_map = {"_title": title_path}

    # Step 2: Parse script segments (if available)
    if script_path and os.path.exists(script_path):
        segments = parse_script_segments(script_path)
        print(f"\nParsed {len(segments)} script segments")
    else:
        # Without a script, create a single segment covering the whole audio
        audio_duration = get_duration(audio_path, ffprobe)
        segments = [{"speaker": "VOICE1", "text": "full audio"}]
        print(f"\nNo script provided -- using single-segment mode")

    # Step 3: Assign graphs to segments
    print("Assigning graphs to segments...")
    assignments = assign_graphs_to_segments(segments, graph_map, concept_map)

    # Step 4: Consolidate consecutive same-image segments
    ranges = consolidate_ranges(assignments)
    print(f"Consolidated into {len(ranges)} visual ranges")

    # Step 5: Estimate segment durations
    # If we have individual segment audio files, use their actual durations
    # Otherwise, divide audio evenly
    total_duration = get_duration(audio_path, ffprobe)
    print(f"Total audio duration: {total_duration:.1f}s ({total_duration/60:.1f} min)")

    # Evenly distribute duration across segments
    seg_duration = total_duration / max(len(segments), 1)
    segment_durations = [seg_duration] * len(segments)

    # Step 6: Build video
    print("\nBuilding video clips...")
    try:
        result = build_video(audio_path, ranges, segment_durations, output_path, ffmpeg, work_dir)

        if result:
            vid_duration = get_duration(result, ffprobe)
            size_mb = os.path.getsize(result) / (1024 * 1024)
            print(f"\n{'=' * 40}")
            print(f"VIDEO COMPLETE: {result}")
            print(f"  Duration: {int(vid_duration // 60)}m {int(vid_duration % 60)}s")
            print(f"  Size: {size_mb:.1f} MB")
            print(f"{'=' * 40}")
            return result
        else:
            print("\nFAILED to create video")
            return None
    finally:
        # Clean up temp files (but keep the output)
        shutil.rmtree(work_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a video podcast with auto-generated concept visuals",
        epilog="Requires: pip install matplotlib numpy pyyaml; ffmpeg installed"
    )
    parser.add_argument("--audio", type=str, required=True,
                        help="Path to the podcast audio file (MP3)")
    parser.add_argument("--pack-dir", type=str, required=True,
                        help="Path to course pack directory (must contain pack.yaml)")
    parser.add_argument("--output", "-o", type=str, default="podcast_video.mp4",
                        help="Output video file path (default: podcast_video.mp4)")
    parser.add_argument("--script", type=str, default=None,
                        help="Path to the podcast script (for better segment-to-visual mapping)")

    args = parser.parse_args()

    if not os.path.exists(args.audio):
        print(f"ERROR: Audio file not found: {args.audio}")
        sys.exit(1)

    if not os.path.exists(os.path.join(args.pack_dir, "pack.yaml")):
        print(f"ERROR: pack.yaml not found in {args.pack_dir}")
        sys.exit(1)

    result = generate_podcast_video(
        audio_path=args.audio,
        pack_dir=args.pack_dir,
        output_path=args.output,
        script_path=args.script,
    )

    if not result:
        sys.exit(1)


if __name__ == "__main__":
    main()
