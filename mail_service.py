"""Simple mail service.

For now: prints to console and appends to mail.log.
TODO: plug in real SMTP / SendGrid / Aliyun DM later.
"""
import os
from datetime import datetime

LOG_PATH = os.path.join(os.path.dirname(__file__), 'mail.log')


def send_email(to: str, subject: str, body: str) -> None:
    line = f"[{datetime.utcnow().isoformat()}] TO={to} SUBJECT={subject}\n{body}\n{'-' * 60}\n"
    print('\n' + line)
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception as e:
        print(f'mail log write failed: {e}')
    # TODO real SMTP:
    # import smtplib; from email.mime.text import MIMEText
    # msg = MIMEText(body, 'plain', 'utf-8'); msg['Subject']=subject
    # msg['From']=os.getenv('SMTP_FROM'); msg['To']=to
    # with smtplib.SMTP_SSL(os.getenv('SMTP_HOST'), int(os.getenv('SMTP_PORT','465'))) as s:
    #     s.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS')); s.send_message(msg)
