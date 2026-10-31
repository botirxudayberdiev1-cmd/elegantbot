"""To'y kadrlaridan Instagram Reels (9:16) montaj.

Kadrlar (video va rasm) papkasidan musiqa ritmiga (beat) mos kesilgan, rang
berilgan (iliq «to'y» ko'rinishi), chiroyli o'tishlar, sarlavha va oxirgi
yozuvli 1080x1920 video yasaydi.

Misol:
    python montaj_reels/reels.py kadrlar/ --music musiqa.mp3 --title "Aziz & Madina" --out reels.mp4

Kerak: ffmpeg/ffprobe (PATH'da) va numpy.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

W, H, FPS = 1080, 1920, 30
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mts", ".m2ts", ".webm", ".3gp"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".tif", ".tiff"}

# Iliq, yumshoq «film» rangi: qora biroz ko'tarilgan, oq yumshatilgan
GRADE = (
    "eq=contrast=1.07:saturation=1.10:brightness=0.01,"
    "colorbalance=rs=0.03:bs=-0.03:rm=0.02:bm=-0.02:rh=0.02:bh=-0.03,"
    "curves=master='0/0.035 0.25/0.24 0.5/0.52 0.75/0.78 1/0.965',"
    "unsharp=5:5:0.4"
)

# O'tishlar: (nomi, davomiyligi). Qisqa kadrlar orasida — deyarli «kesish».
SOFT = [("dissolve", 0.55), ("fadewhite", 0.30), ("smoothleft", 0.40), ("fade", 0.50),
        ("circleopen", 0.50), ("smoothup", 0.40), ("fadewhite", 0.30), ("zoomin", 0.45),
        ("hblur", 0.40), ("radial", 0.45)]
CUT = ("fade", 2 / FPS)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/GABRIOLA.TTF", "C:/Windows/Fonts/georgiai.ttf",
    "C:/Windows/Fonts/timesi.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
    "/usr/share/fonts/truetype/crosextra/Caladea-Italic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]


def run(cmd, quiet=True):
    r = subprocess.run(cmd, capture_output=quiet, text=True)
    if r.returncode != 0:
        sys.stderr.write((r.stderr or "")[-3000:])
        raise SystemExit(f"ffmpeg xato: {' '.join(map(str, cmd[:6]))} ...")
    return r


def probe(path: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    data = json.loads(r.stdout)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    num, _, den = v.get("avg_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den) if float(den or 0) else 0.0
    return {"duration": float(data["format"].get("duration") or 0), "fps": fps}


def ff_path(p) -> str:
    """ffmpeg filtr ichida fayl yo'li (Windows'dagi «C:» ham)."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


# ---------------------------------------------------------------- musiqa ritmi

def load_audio(path: Path, sr=22050) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-t", "600", "-ac", "1", "-ar", str(sr),
                        "-f", "f32le", "-"], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"Musiqani o'qib bo'lmadi: {path}")
    return np.frombuffer(r.stdout, dtype=np.float32)


def beat_track(y: np.ndarray, sr=22050, hop=512, n_fft=2048):
    """Oddiy beat-tracker: spektral flux → tempo (avtokorrelyatsiya) → faza."""
    frames = 1 + max(0, (len(y) - n_fft) // hop)
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    mag = np.abs(np.fft.rfft(y[idx] * np.hanning(n_fft), axis=1))
    mag = np.log1p(10 * mag)
    flux = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")  # mahalliy o'rtachani olib tashlash
    env = np.maximum(flux, 0)
    env /= env.max() or 1

    fr = sr / hop
    ac = np.correlate(env - env.mean(), env - env.mean(), mode="full")[len(env) - 1:]
    lags = np.arange(int(fr * 60 / 180), int(fr * 60 / 70) + 1)
    bpm = 60 * fr / lags
    weight = np.exp(-0.5 * (np.log2(bpm / 115) / 0.9) ** 2)  # ~115 BPM atrofini afzal ko'radi
    period = lags[np.argmax(ac[lags] * weight)]

    # Aniqroq davr (kasr) va faza
    best = (-1, 0, period)
    for p in np.linspace(period - 1, period + 1, 21):
        n = int((len(env) - 1) / p)
        for ph in range(int(p)):
            s = env[np.round(ph + p * np.arange(n)).astype(int)].sum()
            if s > best[0]:
                best = (s, ph, p)
    _, ph, p = best
    beats = (ph + p * np.arange(int((len(env) - 1 - ph) / p) + 1)) / fr
    return beats, p / fr, env, fr


def pick_start(beats, env, fr, need: float) -> int:
    """Eng «kuchli» (naqarot) qismi boshlanadigan beat indeksi."""
    best_i, best_s = 0, -1.0
    step = 4  # taktning boshidan
    for i in range(0, len(beats), step):
        a, b = beats[i], beats[i] + need
        if b > len(env) / fr - 0.5:
            break
        s = env[int(a * fr):int(b * fr)].mean()
        if s > best_s:
            best_i, best_s = i, s
    return best_i


# ---------------------------------------------------------------- kadrlar

def collect(folder: Path):
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXT | PHOTO_EXT)
    if not files:
        raise SystemExit(f"{folder} ichida video yoki rasm topilmadi")
    return files


def fit_filter(fit: str) -> str:
    if fit == "blur":
        return (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"gblur=sigma=45,eq=brightness=-0.10:saturation=0.8[bg];"
                f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2")
    return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"


def render_segment(src: Path, info: dict, length: float, i: int, out: Path, fit: str, preset: str):
    frames = max(1, round(length * FPS))
    if src.suffix.lower() in PHOTO_EXT:
        # Ken Burns: navbat bilan yaqinlashish / uzoqlashish, titramasligi uchun 2x kattalashtirib
        z = f"1+0.10*on/{frames}" if i % 2 == 0 else f"1.10-0.10*on/{frames}"
        vf = (f"scale={2 * W}:{2 * H}:force_original_aspect_ratio=increase,crop={2 * W}:{2 * H},"
              f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
              f"{GRADE}")
        inp = ["-loop", "1", "-framerate", str(FPS), "-t", f"{length + 0.2:.3f}", "-i", str(src)]
    else:
        slow = 2.0 if info["fps"] >= 47 else 1.0  # 50/60 fps → haqiqiy slow-motion
        need = length / slow
        start = max(0.0, (info["duration"] - need) / 2)  # o'rtasidan (eng yaxshi lahza ko'pincha shu yerda)
        inp = ["-ss", f"{start:.3f}", "-t", f"{need + 0.2:.3f}", "-i", str(src)]
        vf = (f"setpts={slow}*(PTS-STARTPTS),fps={FPS},{fit_filter(fit)},{GRADE},"
              f"tpad=stop_mode=clone:stop_duration=2")
    run(["ffmpeg", "-y", "-v", "error", *inp, "-filter_complex", f"[0:v]{vf},format=yuv420p,setsar=1[v]",
         "-map", "[v]", "-frames:v", str(frames), "-an", "-r", str(FPS),
         "-c:v", "libx264", "-preset", preset, "-crf", "12", "-video_track_timescale", "15360", str(out)])


# ---------------------------------------------------------------- reja

def plan(n_media: int, period: float, max_len: float | None):
    """Har kadr necha beat turishi: ritmik naqsh, boshi va oxiri uzunroq."""
    unit = max(1, round(1.1 / period))  # ~1.1 s ga eng yaqin beatlar soni
    pattern = [2, 2, 1, 1, 2, 2, 3, 1, 1, 2, 1, 1]
    counts = []
    for k in range(n_media):
        c = 3 if k == 0 else pattern[(k - 1) % len(pattern)]
        counts.append(c * unit)
    if n_media > 1:
        counts[-1] = 3 * unit
    if max_len:
        total, cut = 0, []
        for c in counts:
            if total + c * period > max_len and len(cut) >= 2:
                break
            cut.append(c)
            total += c * period
        counts = cut
    return counts, unit


def alpha_expr(a, b, f=0.5):
    return (f"if(lt(t,{a}),0,if(lt(t,{a + f}),(t-{a})/{f},"
            f"if(lt(t,{b - f}),1,if(lt(t,{b}),({b}-t)/{f},0))))")


def main():
    ap = argparse.ArgumentParser(description="To'y kadrlaridan Instagram Reels (9:16) montaj")
    ap.add_argument("folder", type=Path, help="kadrlar papkasi (video va rasmlar, nomi bo'yicha tartiblanadi)")
    ap.add_argument("--music", type=Path, help="musiqa fayli (mp3/m4a/wav)")
    ap.add_argument("--music-start", default="auto", help="musiqa boshlanishi (soniya) yoki auto — naqarot")
    ap.add_argument("--duration", type=float, default=None, help="maksimal uzunlik, soniya (masalan 30)")
    ap.add_argument("--title", default="", help="boshidagi yozuv, masalan \"Aziz & Madina\"")
    ap.add_argument("--subtitle", default="", help="ikkinchi qator, masalan \"Wedding day\"")
    ap.add_argument("--end", default="Elegant Media", help="oxiridagi yozuv (bo'sh — yozuvsiz)")
    ap.add_argument("--fit", choices=["crop", "blur"], default="crop",
                    help="gorizontal kadr: crop — butun ekran, blur — xira fon ustida to'liq kadr")
    ap.add_argument("--font", type=Path, help="sarlavha shrifti (.ttf/.otf)")
    ap.add_argument("--grain", type=int, default=5, help="film doni kuchi (0 — yo'q)")
    ap.add_argument("--preview", action="store_true", help="tez, past sifatli sinov")
    ap.add_argument("--out", type=Path, default=Path("reels.mp4"))
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} topilmadi — ffmpeg o'rnating va PATH'ga qo'shing")

    media = collect(args.folder)
    infos = [probe(m) if m.suffix.lower() in VIDEO_EXT else {"duration": 0, "fps": 0} for m in media]

    # Ritm
    if args.music:
        y = load_audio(args.music)
        beats, period, env, fr = beat_track(y)
        print(f"Musiqa: {60 / period:.0f} BPM")
    else:
        period = 0.5
        beats = np.arange(0, 600, period)
        env, fr = None, 1
    counts, unit = plan(len(media), period, args.duration)
    media, infos = media[:len(counts)], infos[:len(counts)]
    need_beats = sum(counts)

    if args.music:
        if args.music_start == "auto":
            b0 = pick_start(beats, env, fr, need_beats * period + 1)
        else:
            b0 = int(np.searchsorted(beats, float(args.music_start)))
        if b0 + need_beats >= len(beats):
            b0 = max(0, len(beats) - need_beats - 1)
            if b0 + need_beats >= len(beats):
                raise SystemExit("Musiqa juda qisqa — --duration ni kamaytiring yoki uzunroq musiqa bering")
        music_t0 = float(beats[b0])
    else:
        b0, music_t0 = 0, 0.0

    # Kesish nuqtalari — haqiqiy beatlar ustida
    cuts, k = [0.0], b0
    for c in counts:
        k += c
        cuts.append(float(beats[k]) - music_t0)
    total = cuts[-1]
    durs = [cuts[i + 1] - cuts[i] for i in range(len(counts))]

    trans, soft_i = [], 0
    for i in range(len(counts) - 1):
        if i == 0:
            trans.append(("fade", 0.6))
        elif counts[i] <= unit or counts[i + 1] <= unit:
            trans.append(CUT)
        else:
            trans.append(SOFT[soft_i % len(SOFT)])
            soft_i += 1
    print(f"{len(media)} ta kadr, {total:.1f} s")

    preset = "ultrafast" if args.preview else "veryfast"
    tmp = Path(tempfile.mkdtemp(prefix="reels_"))
    try:
        segs = []
        for i, (m, info) in enumerate(zip(media, infos)):
            before = trans[i - 1][1] / 2 if i > 0 else 0
            after = trans[i][1] / 2 if i < len(trans) else 0
            seg = tmp / f"seg{i:03d}.mp4"
            print(f"  [{i + 1}/{len(media)}] {m.name}  {durs[i]:.2f} s")
            render_segment(m, info, durs[i] + before + after, i, seg, args.fit, preset)
            segs.append(seg)

        # O'tishlar zanjiri
        parts, last = [], "0:v"
        for k in range(1, len(segs)):
            name, d = trans[k - 1]
            off = cuts[k] - d / 2
            parts.append(f"[{last}][{k}:v]xfade=transition={name}:duration={d:.3f}:offset={off:.3f}[x{k}]")
            last = f"x{k}"

        post = [f"vignette=angle=PI/5"]
        if args.grain:
            post.append(f"noise=alls={args.grain}:allf=t")
        font = args.font or next((Path(f) for f in FONT_CANDIDATES if Path(f).exists()), None)
        fontopt = f"fontfile='{ff_path(font)}':" if font else ""

        def text(s, size, y, a, b, tag):
            tf = tmp / f"{tag}.txt"
            tf.write_text(s, encoding="utf-8")
            return (f"drawtext={fontopt}textfile='{ff_path(tf)}':fontsize={size}:fontcolor=white:"
                    f"shadowcolor=black@0.45:shadowx=2:shadowy=3:x=(w-text_w)/2:y={y}:"
                    f"alpha='{alpha_expr(a, b)}'")

        t_end = min(4.0, total * 0.4)
        if args.title:
            post.append(text(args.title, 110, "h*0.70", 0.4, t_end, "title"))
        if args.subtitle:
            post.append(text(args.subtitle, 56, "h*0.70+135", 0.8, t_end, "sub"))
        if args.end:
            post.append(text(args.end, 64, "h*0.80", max(t_end, total - 2.8), total + 0.5, "end"))
        # Oxirida qoraga sekin o'tish
        post.append(f"fade=t=out:st={total - 0.8:.3f}:d=0.8")
        parts.append(f"[{last}]{','.join(post)},format=yuv420p[vout]")

        cmd = ["ffmpeg", "-y", "-v", "error", "-stats"]
        for s in segs:
            cmd += ["-i", str(s)]
        amap = []
        if args.music:
            cmd += ["-ss", f"{music_t0:.3f}", "-i", str(args.music)]
            parts.append(f"[{len(segs)}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
                         f"afade=t=in:d=0.15,afade=t=out:st={max(0, total - 1.8):.3f}:d=1.8,"
                         f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
            amap = ["-map", "[aout]", "-c:a", "aac", "-b:a", "256k", "-ar", "48000"]
        cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", *amap,
                "-t", f"{total:.3f}", "-r", str(FPS),
                "-c:v", "libx264", "-preset", "ultrafast" if args.preview else "slow",
                "-crf", "28" if args.preview else "17", "-profile:v", "high", "-level", "4.2",
                "-maxrate", "20M", "-bufsize", "40M", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(args.out)]
        print("Yakuniy render...")
        run(cmd, quiet=False)
        print(f"Tayyor: {args.out}  ({total:.1f} s, {W}x{H}, {FPS} fps)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
