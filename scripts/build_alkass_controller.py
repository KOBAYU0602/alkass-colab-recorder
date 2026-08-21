import json
from pathlib import Path


def md(source):
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(True)}


def code(source):
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(True),
    }


cells = [
    md("""# Alkass one–eight — scheduled recorder / DVR extractor

Alkass Shoof の24時間ライブを、**Asia/Amman（UTC+3）の現実時刻**に合わせてMP4保存します。

- チャンネルは各ジョブで `one`〜`eight` を指定できます。
- 未来の区間は開始まで待機し、配信セグメントをDriveへ逐次保存します。
- 進行中・過去の区間は、HLSの `PROGRAM-DATE-TIME` を使って利用可能なDVR範囲から回収します。
- Colab切断後も、同じ実行セルを再実行すればDrive上の台帳から再開します。
- 1080pを優先し、完了後にMP4化してffprobeで解像度・コーデック・時間を検査します。
- AHF大会スケジュールから対戦カードとファイル名を自動生成するモードもあります。

## ログイン情報の安全な渡し方

チャンネル1〜4は通常ログイン不要です。5〜8など契約チャンネルには、次のどちらかを使います。

1. Colab左側の鍵アイコン（Secrets）に `ALKASS_COOKIES` という名前でNetscape Cookie全文を登録する（推奨）
2. Cookieファイルを `/MyDrive/Cookies_Alkass.txt` に置く

CookieやTokenはノートブック本文・状態JSON・ログへ出力しません。

> 2026-08-20の実測では、Alkassの公式1080p HLSに見えているDVR窓は約60分でした。過去指定は実行時に配信元へ残っている範囲だけ回収できます。24時間保持は確認できていません。
"""),
    code("""#@title 1. Google Driveをマウントし、録画設定を入力する
from google.colab import drive
drive.mount('/content/drive')

#@markdown ### 手動ジョブ
#@markdown `channel` は one / two / three / four / five / six / seven / eight。
#@markdown `name` がそのままMP4名になります。
JOBS = [
    # {
    #     "channel": "two",
    #     "start": "2026-08-21 13:55",
    #     "end": "2026-08-21 15:40",
    #     "name": "21082026 Team A vs Team B Alkass Two",
    # },
]

#@markdown ### AHF日程から自動作成（必要な場合だけ True）
USE_AHF_SCHEDULE = False
SCHEDULE_URL = "https://asianhandball.org/amman2026/s/"
SCHEDULE_DATE_FROM = "2026-08-20"
SCHEDULE_DATE_TO = "2026-08-31"
MATCH_PRE_ROLL_MINUTES = 5
MATCH_POST_START_MINUTES = 105

#@markdown 対戦カード名はAHFページ記載どおり。値は録画するAlkassチャンネル。
#@markdown 対応表にない試合は誤録画防止のため自動ジョブにしません。
CHANNEL_BY_MATCH = {
    # "Team A vs Team B": "two",
}

#@markdown MyDriveの保存先
OUTPUT_DIR = "/content/drive/MyDrive/Alkass Recordings"

#@markdown Cookieの予備ファイル。Colab Secret `ALKASS_COOKIES` があればそちらを優先します。
COOKIE_FILE = "/content/drive/MyDrive/Cookies_Alkass.txt"

#@markdown 通常は最大帯域（1080p）を選びます。必要なら 720 に変更できます。
QUALITY_HEIGHT = 1080

#@markdown 過去区間の先頭が消えていたら、不完全MP4を作らずエラーにします。
STRICT_PAST_START = True

#@markdown 設定確認後に True にしてください。
RUN_JOBS = False

TIMEZONE = "Asia/Amman"
API_URL = "https://shoofapi.alkass.net/Shoof/liveV3.php"
SOURCE_PAGE = "https://shoof.alkass.net/live"
VALID_CHANNELS = {"one", "two", "three", "four", "five", "six", "seven", "eight"}

print("設定済み。ジョブとチャンネルを確認し、最後のセルを実行してください。")
"""),
    code(r'''#@title 2. 録画エンジンを読み込む
import os, re, json, time, math, hashlib, subprocess, html as html_lib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
from http.cookiejar import MozillaCookieJar

import requests

!apt-get -qq update >/dev/null
!apt-get -qq install -y ffmpeg >/dev/null

TZ = ZoneInfo(TIMEZONE)
OUT = Path(OUTPUT_DIR)
WORK_ROOT = OUT / ".cloud_work" / "alkass"
OUT.mkdir(parents=True, exist_ok=True)
WORK_ROOT.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Origin": "https://shoof.alkass.net",
    "Referer": SOURCE_PAGE,
})

def load_auth():
    cookie_path = None
    try:
        from google.colab import userdata
        secret = userdata.get("ALKASS_COOKIES")
    except Exception:
        secret = None
    if secret:
        cookie_path = Path("/content/alkass_cookies.txt")
        cookie_path.write_text(secret.rstrip() + "\n", encoding="utf-8")
        os.chmod(cookie_path, 0o600)
    elif Path(COOKIE_FILE).exists():
        cookie_path = Path(COOKIE_FILE)
    if not cookie_path:
        return None, "ログインCookieなし（無料チャンネル用）"
    jar = MozillaCookieJar(str(cookie_path))
    jar.load(ignore_discard=True, ignore_expires=True)
    bearer = None
    count = 0
    for c in jar:
        SESSION.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
        count += 1
        if c.name.lower() == "token":
            bearer = c.value
    return bearer, f"Cookie {count}件を安全に読み込み済み"

BEARER_TOKEN, AUTH_NOTE = load_auth()
print(AUTH_NOTE)

def api_headers():
    return {"Authorization": f"Bearer {BEARER_TOKEN}"} if BEARER_TOKEN else {}

def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def parse_dt(value):
    value = value.strip()
    if "T" in value or re.search(r"[+-]\d\d:\d\d$", value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)
    fmt = "%Y-%m-%d %H:%M:%S" if value.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(value, fmt).replace(tzinfo=TZ)

def parse_pdt(value):
    value = value.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(value).astimezone(TZ)

def safe_name(value):
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", value).strip().rstrip(".")
    return value or "Alkass_Record"

def slug(value):
    return re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("_") or "job"

TEAM_NAME_MAP = {"Republic of Korea": "Korea", "I. R. Iran": "Iran", "P. R. China": "China"}

def display_team(team):
    return TEAM_NAME_MAP.get(team.strip(), team.strip())

def build_schedule_jobs():
    r = SESSION.get(SCHEDULE_URL, timeout=30)
    r.raise_for_status()
    page = r.text
    rows = re.findall(r'<tr[^>]+itemtype=["\']http://schema.org/SportsEvent["\'][^>]*>(.*?)</tr>', page, re.I | re.S)
    date_from = datetime.strptime(SCHEDULE_DATE_FROM, "%Y-%m-%d").date()
    date_to = datetime.strptime(SCHEDULE_DATE_TO, "%Y-%m-%d").date()
    mapping = {k.strip().casefold(): v.strip().lower() for k, v in CHANNEL_BY_MATCH.items()}
    jobs = []
    for row in rows:
        dm = re.search(r'<time[^>]+datetime=["\']([^"\']+)["\']', row, re.I)
        tm = re.search(r'<h4[^>]*class=["\'][^"\']*sp-event-title[^"\']*["\'][^>]*>\s*<a[^>]*>(.*?)</a>', row, re.I | re.S)
        if not dm or not tm:
            continue
        title = html_lib.unescape(re.sub(r"<[^>]+>", "", tm.group(1))).strip()
        channel = mapping.get(title.casefold())
        if not channel:
            continue
        kickoff = parse_dt(dm.group(1))
        if not (date_from <= kickoff.date() <= date_to):
            continue
        if channel not in VALID_CHANNELS:
            raise ValueError(f"{title}: 不正なchannel {channel}")
        if " vs " not in title:
            continue
        a, b = [x.strip() for x in title.split(" vs ", 1)]
        start = kickoff - timedelta(minutes=MATCH_PRE_ROLL_MINUTES)
        end = kickoff + timedelta(minutes=MATCH_POST_START_MINUTES)
        name = f"{kickoff:%d%m%Y} U-19 {display_team(a)} vs U-19 {display_team(b)}"
        jobs.append({"channel": channel, "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                     "end": end.strftime("%Y-%m-%d %H:%M:%S"), "name": name,
                     "schedule_title": title})
    if not jobs:
        raise RuntimeError("CHANNEL_BY_MATCHと日付範囲に一致するAHF試合がありません。")
    return sorted(jobs, key=lambda j: parse_dt(j["start"]))

def request_text(url, headers=None, timeout=30):
    r = SESSION.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.text

def discover_channel(channel):
    channel = channel.lower().strip()
    if channel not in VALID_CHANNELS:
        raise ValueError(f"channelはone〜eight: {channel}")
    r = SESSION.get(API_URL, headers=api_headers(), timeout=30)
    r.raise_for_status()
    items = r.json()
    item = next((x for x in items if str(x.get("webname", "")).lower() == channel), None)
    if not item:
        raise RuntimeError(f"公式APIにチャンネル {channel} がありません。")
    master = item.get("body") or ""
    if not master:
        if item.get("is_locked"):
            raise RuntimeError(f"Alkass {channel} はロック中です。Colab Secret ALKASS_COOKIES またはCookies_Alkass.txtを更新してください。")
        raise RuntimeError(f"Alkass {channel} の配信URLが空です。放送停止中の可能性があります。")
    return {"channel": channel, "title": item.get("title") or f"Alkass {channel}", "master_url": master,
            "locked": bool(item.get("is_locked")), "premium": item.get("is_premium")}

def choose_media(master_url):
    text = request_text(master_url)
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    variants = []
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF") and i + 1 < len(lines):
            bw = re.search(r"(?:AVERAGE-)?BANDWIDTH=(\d+)", line)
            res = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
            variants.append({"url": urljoin(master_url, lines[i+1]),
                             "bandwidth": int(bw.group(1)) if bw else 0,
                             "width": int(res.group(1)) if res else 0,
                             "height": int(res.group(2)) if res else 0})
    if not variants:
        return master_url, {"width": 0, "height": 0, "bandwidth": 0}
    exact = [v for v in variants if v["height"] == int(QUALITY_HEIGHT)]
    below = [v for v in variants if v["height"] <= int(QUALITY_HEIGHT)]
    selected = max(exact or below or variants, key=lambda v: (v["height"], v["bandwidth"]))
    return selected["url"], selected

def parse_media(media_url):
    text = request_text(media_url)
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    seq0 = 0
    disc_seq = 0
    for line in lines:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            seq0 = int(line.split(":", 1)[1])
        if line.startswith("#EXT-X-DISCONTINUITY-SEQUENCE:"):
            disc_seq = int(line.split(":", 1)[1])
    segments = []
    pdt = None
    duration = None
    discontinuity = False
    idx = 0
    for line in lines:
        if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            pdt = parse_pdt(line.split(":", 1)[1])
        elif line.startswith("#EXTINF:"):
            duration = float(line.split(":", 1)[1].split(",", 1)[0])
        elif line == "#EXT-X-DISCONTINUITY":
            disc_seq += 1
            discontinuity = True
        elif not line.startswith("#"):
            if pdt is None or duration is None:
                raise RuntimeError("HLSにPROGRAM-DATE-TIMEまたはEXTINFがありません。")
            segments.append({"seq": seq0 + idx, "pdt": pdt, "duration": duration,
                             "url": urljoin(media_url, line), "discontinuity": discontinuity,
                             "disc_seq": disc_seq})
            pdt = pdt + timedelta(seconds=duration)
            duration = None
            discontinuity = False
            idx += 1
    if not segments:
        raise RuntimeError("メディアプレイリストが空です。")
    return segments

def valid_ts(path):
    path = Path(path)
    if not path.exists() or path.stat().st_size < 1880:
        return False
    return path.stat().st_size % 188 == 0

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def load_ledger(path, job):
    path = Path(path)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("job", {}).get("channel") == job["channel"]:
                return data
        except Exception:
            pass
    return {"version": 1, "status": "capturing", "job": job, "segments": {}, "gaps": [],
            "created_at": datetime.now(TZ).isoformat(), "updated_at": datetime.now(TZ).isoformat()}

def download_segment(seg, path, retries=10):
    path = Path(path)
    if valid_ts(path):
        return path.stat().st_size, sha256_file(path)
    part = path.with_suffix(path.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with SESSION.get(seg["url"], timeout=45, stream=True) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
            if valid_ts(part):
                os.replace(part, path)
                return path.stat().st_size, sha256_file(path)
            part.unlink(missing_ok=True)
        except Exception as e:
            part.unlink(missing_ok=True)
            if attempt == retries:
                raise
            time.sleep(min(30, 2 ** min(attempt, 5)))

def ffprobe(path):
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "format=duration,size:stream=index,codec_type,codec_name,width,height", "-of", "json", str(path)]
    return json.loads(subprocess.check_output(cmd, text=True))

def analyze_gaps(records, start, end):
    records = sorted(records, key=lambda x: x["pdt"])
    gaps = []
    if not records:
        return [{"type": "all_missing", "seconds": (end-start).total_seconds()}]
    first = parse_dt(records[0]["pdt"])
    last_end = parse_dt(records[-1]["pdt"]) + timedelta(seconds=records[-1]["duration"])
    if first > start + timedelta(seconds=7):
        gaps.append({"type": "missing_start", "from": start.isoformat(), "to": first.isoformat(),
                     "seconds": round((first-start).total_seconds(), 3)})
    prev = records[0]
    for cur in records[1:]:
        expected = parse_dt(prev["pdt"]) + timedelta(seconds=prev["duration"])
        actual = parse_dt(cur["pdt"])
        if actual > expected + timedelta(seconds=0.5):
            gaps.append({"type": "media_gap", "after_seq": prev["seq"], "before_seq": cur["seq"],
                         "from": expected.isoformat(), "to": actual.isoformat(),
                         "seconds": round((actual-expected).total_seconds(), 3),
                         "missing_sequences": max(0, int(cur["seq"]) - int(prev["seq"]) - 1)})
        prev = cur
    if last_end < end - timedelta(seconds=7):
        gaps.append({"type": "missing_end", "from": last_end.isoformat(), "to": end.isoformat(),
                     "seconds": round((end-last_end).total_seconds(), 3)})
    return gaps

def mux_job(job, ledger, work_dir, final_path):
    records = list(ledger["segments"].values())
    records.sort(key=lambda x: x["pdt"])
    concat = work_dir / "concat.txt"
    concat.write_text("".join(f"file '{(work_dir / r['path']).as_posix()}'\n" for r in records), encoding="utf-8")
    joined = work_dir / "joined.ts"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat), "-c", "copy", str(joined)], check=True)
    start = parse_dt(job["start"])
    first = parse_dt(records[0]["pdt"])
    offset = max(0.0, (start-first).total_seconds())
    wanted = (parse_dt(job["end"])-start).total_seconds()
    temp_mp4 = work_dir / (final_path.name + ".tmp.mp4")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-ss", f"{offset:.3f}",
                    "-i", str(joined), "-t", f"{wanted:.3f}", "-map", "0:v:0", "-map", "0:a:0?",
                    "-c", "copy", "-movflags", "+faststart", str(temp_mp4)], check=True)
    os.replace(temp_mp4, final_path)
    return ffprobe(final_path)

def record_job(raw_job):
    job = dict(raw_job)
    job["channel"] = job.get("channel", "").lower().strip()
    if job["channel"] not in VALID_CHANNELS:
        raise ValueError(f"不正なchannel: {job['channel']}")
    start, end = parse_dt(job["start"]), parse_dt(job["end"])
    if end <= start:
        raise ValueError("endはstartより後にしてください。")
    name = safe_name(job["name"])
    final_path = OUT / (name if name.lower().endswith(".mp4") else name + ".mp4")
    key = f"{start:%Y%m%d%H%M%S}_{job['channel']}_{slug(name)}"
    work_dir = WORK_ROOT / key
    seg_dir = work_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = work_dir / "ledger.json"
    state_path = work_dir / "state.json"
    ledger = load_ledger(ledger_path, job)
    if final_path.exists():
        try:
            probe = ffprobe(final_path)
            state = {"status": "completed", "job": job, "final": str(final_path), "probe": probe,
                     "updated_at": datetime.now(TZ).isoformat(), "note": "既存MP4を検証してスキップ"}
            atomic_json(state_path, state)
            print(f"既存完了: {final_path.name}")
            return state
        except Exception:
            raise RuntimeError(f"同名MP4が存在しますが読めません。上書き防止のため停止: {final_path}")

    print(f"\n=== {job['channel']} {start:%Y-%m-%d %H:%M} → {end:%H:%M} / {final_path.name} ===")
    last_discovery = 0
    media_url = None
    selected = None
    last_playlist_end = None
    past_start_checked = False
    idle_polls = 0
    while True:
        now = datetime.now(TZ)
        if now < start - timedelta(minutes=3):
            wait = min(60, (start - timedelta(minutes=3) - now).total_seconds())
            print(f"開始前待機: {now:%Y-%m-%d %H:%M:%S} / 約{wait:.0f}秒")
            time.sleep(max(1, wait))
            continue
        try:
            if media_url is None or time.time() - last_discovery > 300:
                info = discover_channel(job["channel"])
                media_url, selected = choose_media(info["master_url"])
                last_discovery = time.time()
                print(f"配信取得: {info['title']} / {selected.get('width')}x{selected.get('height')}")
            playlist = parse_media(media_url)
        except Exception as e:
            print(f"配信再取得待ち: {type(e).__name__}: {e}")
            media_url = None
            time.sleep(15)
            continue

        p_first = playlist[0]["pdt"]
        p_end = playlist[-1]["pdt"] + timedelta(seconds=playlist[-1]["duration"])
        last_playlist_end = p_end
        if not past_start_checked:
            print(f"現在のDVR窓: {p_first:%Y-%m-%d %H:%M:%S} → {p_end:%Y-%m-%d %H:%M:%S} "
                  f"({(p_end-p_first).total_seconds()/60:.1f}分)")
            past_start_checked = True
            if datetime.now(TZ) > start and start < p_first - timedelta(seconds=7) and STRICT_PAST_START:
                state = {"status": "unavailable_start", "job": job, "requested_start": start.isoformat(),
                         "available_from": p_first.isoformat(), "available_to": p_end.isoformat(),
                         "message": "指定開始時刻が現在のAlkass DVR窓より古く、先頭を回収できません。",
                         "updated_at": datetime.now(TZ).isoformat()}
                atomic_json(state_path, state)
                raise RuntimeError(state["message"])

        candidates = [s for s in playlist if s["pdt"] < end and s["pdt"] + timedelta(seconds=s["duration"]) > start]
        added = 0
        for seg in candidates:
            skey = f"{seg['disc_seq']}:{seg['seq']}"
            existing = ledger["segments"].get(skey)
            if existing and valid_ts(work_dir / existing["path"]):
                continue
            path = seg_dir / f"d{seg['disc_seq']:04d}_s{seg['seq']:012d}.ts"
            try:
                size, digest = download_segment(seg, path)
            except Exception as e:
                print(f"セグメント保留 seq={seg['seq']}: {e}")
                media_url = None
                continue
            ledger["segments"][skey] = {"seq": seg["seq"], "disc_seq": seg["disc_seq"],
                "pdt": seg["pdt"].isoformat(), "duration": seg["duration"],
                "path": str(path.relative_to(work_dir)), "size": size, "sha256": digest}
            added += 1
            if added % 20 == 0:
                ledger["updated_at"] = datetime.now(TZ).isoformat()
                atomic_json(ledger_path, ledger)
        ledger["updated_at"] = datetime.now(TZ).isoformat()
        atomic_json(ledger_path, ledger)
        duration_have = sum(float(x["duration"]) for x in ledger["segments"].values())
        print(f"進捗: {len(ledger['segments'])} segments / {duration_have/60:.1f}分 (+{added})")

        now = datetime.now(TZ)
        if added == 0:
            idle_polls += 1
        else:
            idle_polls = 0
        if now >= end + timedelta(seconds=12) and p_end >= end:
            break
        if now >= end + timedelta(minutes=2) and idle_polls >= 3:
            break
        time.sleep(6)

    records = list(ledger["segments"].values())
    gaps = analyze_gaps(records, start, end)
    ledger["gaps"] = gaps
    ledger["status"] = "completed_with_gaps" if gaps else "completed"
    atomic_json(ledger_path, ledger)
    if not records:
        raise RuntimeError("指定区間のセグメントを1件も回収できませんでした。")
    probe = mux_job(job, ledger, work_dir, final_path)
    videos = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    audios = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if not videos or float(probe.get("format", {}).get("duration", 0)) <= 1:
        raise RuntimeError("完成MP4の検証に失敗しました。")
    state = {"status": ledger["status"], "job": job, "final": str(final_path),
             "selected_variant": selected, "segments": len(records), "gaps": gaps,
             "probe": probe, "video": videos[0], "audio": audios[0] if audios else None,
             "updated_at": datetime.now(TZ).isoformat()}
    atomic_json(state_path, state)
    print(f"完了: {final_path}")
    print(json.dumps({"status": state["status"], "gaps": gaps, "probe": probe}, ensure_ascii=False, indent=2))
    return state

print("録画エンジン準備完了")
'''),
    code("""#@title 3. ジョブ一覧を確認する（録画はまだ開始しません）
PLANNED_JOBS = build_schedule_jobs() if USE_AHF_SCHEDULE else JOBS

for i, job in enumerate(PLANNED_JOBS, 1):
    ch = job.get("channel", "").lower().strip()
    if ch not in VALID_CHANNELS:
        raise ValueError(f"Job {i}: channelはone〜eightで指定してください: {ch}")
    start, end = parse_dt(job["start"]), parse_dt(job["end"])
    print(f"{i:02d}. Alkass {ch:>5} | {start:%Y-%m-%d %H:%M}–{end:%H:%M} | {job['name']}.mp4")

print(f"合計 {len(PLANNED_JOBS)} ジョブ")
"""),
    code("""#@title 4. 録画を開始／再開する
if not RUN_JOBS:
    raise RuntimeError("安全停止: 設定セルで RUN_JOBS=True にしてから再実行してください。")

RESULTS = []
for job in PLANNED_JOBS:
    RESULTS.append(record_job(job))

batch_state = {
    "status": "completed" if all(x["status"] == "completed" for x in RESULTS) else "completed_with_gaps",
    "results": RESULTS,
    "updated_at": datetime.now(TZ).isoformat(),
}
atomic_json(WORK_ROOT / "batch_state.json", batch_state)
print("全ジョブ終了")
print(json.dumps(batch_state, ensure_ascii=False, indent=2))
"""),
]

nb = {
    "cells": cells,
    "metadata": {
        "colab": {"provenance": [], "toc_visible": True},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 0,
}

out = Path(__file__).resolve().parents[1] / "notebooks" / "Alkass_Controller.ipynb"
out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
print(out)
