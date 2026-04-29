#!/usr/bin/env python3
"""
WEBBSITE — EMAIL AI Agent
Agency World Backend
Reads leads from Google Sheet, generates personalized emails with AI image, sends via Gmail.
"""

import json
import os
import re
import glob
import smtplib
import subprocess
import urllib.request
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import gspread
from google.oauth2.service_account import Credentials

from config import (
    CLAUDE_API_KEY, GMAIL_USER, GMAIL_PASSWORD,
    GOOGLE_SHEETS_CREDS, SPREADSHEET_ID, REPORT_EMAILS
)

claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY)


def get_worksheet():
    creds = Credentials.from_service_account_file(
        GOOGLE_SHEETS_CREDS,
        scopes=[
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID).worksheet('Lead Tracker')


def fetch_website_text(url):
    if not url or url.startswith('https://www.google.com/maps'):
        return ''
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:2000]
    except Exception:
        return ''


def generate_content(business):
    website_text = fetch_website_text(business.get('Website', ''))

    prompt = f"""You are the EMAIL AI agent for WEBBSITE, a premium web design agency in Miami.

Business details:
- Name: {business['Business Name']}
- Industry: {business['Industry']}
- Email: {business['Email']}
- Website: {business['Website']}
- Rating: {business['Rating']} stars | Reviews: {business['Reviews']}
- Address: {business['Address']}
- Website content: {website_text}

Return a JSON object with exactly these fields:
{{
  "contact_name": "First name to address (guess from email prefix or use business name)",
  "subject": "Compelling email subject line specific to their business (max 60 chars)",
  "email_body": "Personalized email under 150 words. Reference something specific about their website or business. Mention 1-2 concrete improvements. Offer a free mockup. NO generic lines. Sign off: Diego Salas | WEBBSITE | webbsite.us@gmail.com",
  "image_prompt": "Detailed prompt for a wide photorealistic banner image relevant to their industry. Premium, editorial quality. Example for a chef: 'Elegant Miami chef plating gourmet food, luxury restaurant, warm lighting, wide banner'",
  "main_problem": "One sentence: the main website problem you found"
}}

Return only valid JSON, no markdown, no extra text."""

    msg = claude.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=900,
        messages=[{'role': 'user', 'content': prompt}]
    )

    return json.loads(msg.content[0].text)


def generate_image(prompt, business_name):
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', business_name)[:25]
    filename = f'webbsite_{safe_name}'
    subprocess.run(
        ['nano-banana', prompt, '--output', filename, '--aspect', '16:9', '--size', '1K'],
        capture_output=True, timeout=60, cwd='/tmp'
    )
    files = glob.glob(f'/tmp/{filename}*')
    return files[0] if files else None


def build_html_email(content, image_path=None):
    paragraphs = content['email_body'].strip().split('\n\n')
    body_html = ''.join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.8;color:#222222;">{p.replace(chr(10), "<br>")}</p>'
        for p in paragraphs if p.strip()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:Georgia,'Times New Roman',serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td style="padding:0 0 2px 0;background:#E8720C;"></td></tr>
    <tr><td style="padding:40px 48px 16px;">
      {body_html}
    </td></tr>
    <tr><td style="padding:0 48px 40px;">
      <table cellpadding="0" cellspacing="0" border="0">
        <tr><td style="border-top:1px solid #eeeeee;padding-top:20px;">
          <p style="margin:0;font-family:Arial,sans-serif;font-size:13px;font-weight:700;letter-spacing:2px;color:#E8720C;">WEBBSITE</p>
          <p style="margin:3px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#999999;">webbsite.us@gmail.com &nbsp;·&nbsp; Miami, FL</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_gmail(to_email, subject, html_body, text_body):
    msg = MIMEMultipart('alternative')
    msg['From'] = f'Diego Salas | WEBBSITE <{GMAIL_USER}>'
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.send_message(msg)


def update_row(ws, row_num, headers, status, ai_message, problem):
    def col(name):
        return headers.index(name) + 1
    ws.update_cell(row_num, col('Status'), status)
    ws.update_cell(row_num, col('Last Contacted'), datetime.now().strftime('%Y-%m-%d %H:%M'))
    ws.update_cell(row_num, col('AI Message'), ai_message)
    if 'Main Problem Detected' in headers:
        ws.update_cell(row_num, col('Main Problem Detected'), problem)


def send_daily_report(results):
    sent = [r for r in results if r['status'] == 'sent']
    failed = [r for r in results if r['status'] != 'sent']
    date_str = datetime.now().strftime('%B %d, %Y')

    lines = [
        f"WEBBSITE — Daily Lead Report",
        f"Date: {date_str}",
        f"",
        f"Emails sent:  {len(sent)}",
        f"Failed:       {len(failed)}",
        f"Total:        {len(results)}",
        f"",
        f"--- LEADS CONTACTED ---",
    ]
    for r in sent:
        lines.append(f"[OK] {r['name']}")
        lines.append(f"     Email: {r['email']}")
        lines.append(f"     Problem found: {r['problem']}")
        lines.append("")

    if failed:
        lines.append("--- FAILED ---")
        for r in failed:
            lines.append(f"[X]  {r['name']} — {r['error']}")

    body = '\n'.join(lines)
    subject = f"WEBBSITE Lead Report — {date_str}"

    for email in REPORT_EMAILS:
        try:
            send_gmail(email, subject, f"<pre style='font-family:monospace'>{body}</pre>", body)
            print(f"  Report sent to {email}")
        except Exception as e:
            print(f"  Report failed to {email}: {e}")


def run(max_leads=5, dry_run=False):
    print(f"\n{'='*50}")
    print(f"WEBBSITE EMAIL AI AGENT")
    print(f"{'='*50}")
    print(f"Mode: {'DRY RUN (no emails sent)' if dry_run else 'LIVE'}")
    print(f"Max leads: {max_leads}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    ws = get_worksheet()
    all_rows = ws.get_all_values()
    headers = all_rows[3]
    results = []

    for i, row in enumerate(all_rows[4:], start=5):
        if len(results) >= max_leads:
            break

        d = dict(zip(headers, row))
        if d.get('Status') != 'New' or not d.get('Email'):
            continue

        print(f"[{len(results)+1}/{max_leads}] {d['Business Name']}")
        print(f"  Email: {d['Email']}")

        try:
            # Generate content with Claude
            print("  Generating personalized content...")
            content = generate_content(d)
            print(f"  Subject: {content['subject']}")
            print(f"  Problem: {content['main_problem']}")

            # Generate image
            print("  Generating image with nano-banana...")
            image_path = generate_image(content['image_prompt'], d['Business Name'])
            print(f"  Image: {image_path or 'failed (will send without)'}")

            # Build HTML email
            html = build_html_email(content, image_path)

            if not dry_run:
                # Send email
                send_gmail(d['Email'], content['subject'], html, content['email_body'])
                print(f"  Sent!")

                # Update sheet
                update_row(ws, i, headers, 'Email Sent', content['email_body'], content['main_problem'])
                print(f"  Sheet updated.")

            results.append({
                'name': d['Business Name'],
                'email': d['Email'],
                'status': 'sent',
                'problem': content['main_problem']
            })

        except Exception as e:
            print(f"  ERROR: {e}")
            if not dry_run:
                update_row(ws, i, headers, 'Error', str(e), '')
            results.append({
                'name': d['Business Name'],
                'email': d['Email'],
                'status': 'error',
                'error': str(e),
                'problem': ''
            })

        print()

    print(f"{'='*50}")
    print(f"Done: {len([r for r in results if r['status'] == 'sent'])} emails sent")

    if not dry_run:
        print("Sending daily report...")
        send_daily_report(results)

    return results


if __name__ == '__main__':
    import sys
    dry = '--dry-run' in sys.argv
    limit = 5
    for arg in sys.argv[1:]:
        if arg.startswith('--limit='):
            limit = int(arg.split('=')[1])
    run(max_leads=limit, dry_run=dry)
