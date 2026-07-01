# N_m3u8DL-RE Telegram Bot

Telegram bot that wraps the [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) stream downloader. Supports all DASH/HLS/MSS download features with real-time progress and auto-upload to Telegram.

## Commands

| Command | Description |
|---------|-------------|
| `/start`, `/help` | Show welcome card with usage instructions |
| `/dl <url> [flags]` | Download a stream with optional N_m3u8DL-RE flags |
| `/flags` | List all supported N_m3u8DL-RE flags |
| `/cancel` | Cancel the current running task |
| `/status` | Show status of active tasks |

You can also paste a bare URL (without `/dl`) and the bot will queue it with default settings.

## Usage Examples

```
# Basic download (auto-selects best tracks)
/dl https://example.com/master.m3u8

# Select best video + audio, mux to MP4
/dl https://example.com/stream.mpd -sv best -sa best -M format=mp4

# Download with custom headers and thread count
/dl https://example.com/playlist.m3u8 -H "Cookie: session=abc" --thread-count 16

# Download 1080p HEVC video only
/dl https://example.com/master.m3u8 -sv res="1920*":codecs=hvc1:for=best

# Live stream recording with time limit
/dl https://example.com/live.m3u8 --live-record-limit 01:00:00 --live-real-time-merge

# Download with decryption key
/dl https://example.com/encrypted.m3u8 --key KID:KEY --decryption-engine MP4DECRYPT

# Subtitle only download
/dl https://example.com/master.m3u8 --sub-only --sub-format SRT

# Download with speed limit and proxy
/dl https://example.com/stream.mpd -R 10M --custom-proxy http://proxy:8080

# Mux to MKV using mkvmerge
/dl https://example.com/master.m3u8 -M format=mkv:muxer=mkvmerge
```

## Setup

### Prerequisites
- Python 3.10+
- N_m3u8DL-RE binary (download from [releases](https://github.com/nilaoda/N_m3u8DL-RE/releases))
- FFmpeg (for muxing)
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Telegram API credentials (from [my.telegram.org](https://my.telegram.org))

### Local

```bash
# Install dependencies
pip install -r requirements.txt

# Configure
cp bot.env.example .env
# Edit .env with your credentials

# Run
python -m n_m3u8dl_bot
```

### Docker

```bash
docker build -t n_m3u8dl-bot .
docker run -d --env-file .env -v ./data:/data n_m3u8dl-bot
```

## All Supported Flags

All N_m3u8DL-RE CLI flags are passed through directly. Use `/flags` in the bot to see the full list, or refer to the [N_m3u8DL-RE documentation](https://github.com/nilaoda/N_m3u8DL-RE#command-line-parameters).

### Key flags:

- `--save-name <name>` - Set output filename
- `--save-pattern <template>` - Naming template with variables
- `--thread-count <n>` - Download thread count
- `-sv/--select-video <opts>` - Select video streams by regex
- `-sa/--select-audio <opts>` - Select audio streams by regex
- `-ss/--select-subtitle <opts>` - Select subtitle streams by regex
- `-dv/--drop-video <opts>` - Drop video streams by regex
- `-da/--drop-audio <opts>` - Drop audio streams by regex
- `-ds/--drop-subtitle <opts>` - Drop subtitle streams by regex
- `-M/--mux-after-done <opts>` - Mux after download (format=mp4/mkv)
- `-H/--header <header>` - Custom HTTP headers
- `-R/--max-speed <speed>` - Speed limit (e.g. 15M, 100K)
- `-mt/--concurrent-download` - Parallel audio/video/subtitle download
- `--auto-select` - Auto-select best tracks (enabled by default)
- `--key <KID:KEY>` - Decryption keys
- `--custom-proxy <url>` - HTTP proxy
- `--live-record-limit <HH:mm:ss>` - Live recording time limit
- `--sub-only` - Download subtitles only
- `--sub-format <SRT|VTT>` - Subtitle output format
