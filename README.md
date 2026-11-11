# Sawasdee Guide

AI-powered Thailand trip guide with tips from a Thai local, shared trips and an expense splitter.
Built with Flask, AWS Bedrock and plain HTML/JS, hosted on AWS EC2 with Nginx.

## Features
- AI itinerary planner (Bedrock)
- "Ask a Thai local" assistant using curated local tips (`tips.json`)
- Shared trips: create a trip, share the 8-character code, and everyone sees the same plan and expenses (refreshes every few seconds)
- Expense splitter for travel companions (equal split, THB)

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
