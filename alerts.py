import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from utils import load_encrypted_password
import os

load_dotenv()

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = load_encrypted_password()
EMAIL_TO = os.getenv("EMAIL_TO")
SMS_TO = os.getenv("SMS_TO", None)




# Replace 'my_email_account' with the name you use for your email account in Keychain
# print(EMAIL_PASS)

def send_alert(alert):
    body = (
        f"ALERT: Inexpensive Call Found\n\n"
        f"Ticker: {alert['Ticker']}\n"
        f"Strike: {alert['Strike']}\n"
        f"Price: ${alert['Price']}\n"
        f"Delta: {alert['Delta']}\n"
        f"Expiration: {alert['Expiration']}\n"
        f"Volume: {alert['Volume']}\n"
        f"OI: {alert['OI']}\n"
        f"Time: {alert['Timestamp']}\n"
    )

    # Send Email
    msg = MIMEMultipart()
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg['Subject'] = f"[Cheap Call] {alert['Ticker']} ${alert['Strike']}"

    msg.attach(MIMEText(body, 'plain'))

    with smtplib.SMTP_SSL(os.getenv("EMAIL_HOST"), int(os.getenv("EMAIL_PORT"))) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.send_message(msg)

        # Send SMS via Email-to-Text (optional)
        if SMS_TO:
            sms_msg = MIMEText(f"{alert['Ticker']} {alert['Strike']}C @ {alert['Price']}, {alert['Expiration']}")
            sms_msg['From'] = EMAIL_FROM
            sms_msg['To'] = SMS_TO
            server.send_message(sms_msg)