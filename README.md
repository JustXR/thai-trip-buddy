# Sawasdee Guide

AI-powered Thailand trip guide with tips from a Thai local, shared trips and an expense splitter.
Built with Flask, AWS Bedrock (Claude Haiku 4.5) and plain HTML/JS, hosted on AWS EC2 with Nginx and gunicorn.

**Live app:** http://sawasdee-guide.duckdns.org (also reachable at http://13.62.70.46)

## Features
- AI itinerary planner (Bedrock) that works in local dishes and hidden gems
- "Ask a Thai local" chat using curated local tips (`tips.json`)
- Shared trips: create a trip, share the 8-character code, and everyone sees the same plan and expenses (refreshes every few seconds)
- Shared expense splitter with a clear "who owes whom" summary (THB)
- Local food guide: 43 dishes with spice levels, regions and filters
- Hidden gems: 19 lesser-known places with opening hours
- Easy Thai phrases with audio
- Dark and light theme, responsive layout for phone and desktop
- Rate limit of 20 AI requests per hour per IP

## Tech stack
| Layer | Technology |
|---|---|
| Front end | Plain HTML, CSS and JavaScript (single page, no build step) |
| Back end | Python, Flask |
| AI | AWS Bedrock, Claude Haiku 4.5 (via boto3) |
| Database | SQLite |
| Web server | Nginx (reverse proxy) and gunicorn |
| Hosting | AWS EC2 (Ubuntu), Elastic IP |
| Security | IAM role (no stored keys), security group, rate limit per IP |
| Process management | systemd service |
| Audio | Pre-recorded Thai audio files (generated once with edge-tts) |
| Version control | Git and GitHub |

## Run locally
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set BEDROCK_MODEL_ID
export $(grep -v '^#' .env | xargs)
python app.py          # http://127.0.0.1:5000
```
Local runs need AWS credentials (`aws configure`) with Bedrock access.
On EC2, use an IAM role instead, so no keys are stored.

## Data
Trips and expenses are stored in a local SQLite file (`trips.db`, created automatically, not committed to Git). Anyone with a trip code can view and edit that trip.

## Deploy (outline)
1. Launch EC2 (Ubuntu), security group: 80/443 open, 22 from your IP only
2. Attach an IAM role with Bedrock invoke permissions
3. Install Nginx and Python, clone this repo, create a venv
4. Run with gunicorn as a systemd service (`gunicorn -w 2 -b 127.0.0.1:5000 app:app`)
5. Nginx proxies `/` to 127.0.0.1:5000 and sets `X-Real-IP`
6. Attach an Elastic IP
