# alerts.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.fernet import Fernet
import os
from dotenv import load_dotenv
import time


def send_alert(message,debug:bool = False):
    load_dotenv()

    EMAIL_FROM = os.getenv("EMAIL_FROM")
    EMAIL_PASS = load_encrypted_password()
    EMAIL_TO = os.getenv("EMAIL_TO")
    SMS_TO = os.getenv("SMS_TO", None)
    
    # Send Email
    #msg = MIMEMultipart()
    #msg['From'] = EMAIL_FROM
    #msg['To'] = EMAIL_TO
    #msg['Subject'] = f"[Cheap Call] {alert['Ticker']} ${alert['Strike']}"

    #msg.attach(MIMEText(body, 'plain'))

    with smtplib.SMTP_SSL(os.getenv("EMAIL_HOST"), int(os.getenv("EMAIL_PORT"))) as server:
        try:
            server.login(EMAIL_FROM, EMAIL_PASS)
            
            #Send Email
            #server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())  # Send the email
            #print(f"Email sent to {EMAIL_FROM}")

            # Send SMS via Email-to-Text (optional)
            if SMS_TO:
                sms_msg = MIMEText(message)
                sms_msg['From'] = EMAIL_FROM
                sms_msg['To'] = SMS_TO
                server.send_message(sms_msg)
                if debug:
                    logMessage(f"Text sent to {SMS_TO}")
        except Exception as e:
            logMessage(e)

def send_alert_alternate(message):
    to_number = os.getenv("SMS_TO")
    smtp_server = os.getenv("EMAIL_HOST")
    smtp_port = int(os.getenv("EMAIL_PORT"))
    smtp_user = os.getenv("EMAIL_FROM")
    smtp_pass = os.getenv("SMTP_PASSWORD")

    if not all([to_number, smtp_server, smtp_user, smtp_pass]):
        logMessage(f"[ALERT] {message}")
        return

    from_addr = smtp_user
    to_addr = to_number

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_addr, to_addr, message)
        server.quit()
        logMessage(f"[Alert sent] {message}")
    except Exception as e:
        logMessage(f"[Alert error] {e}")


#Load password for notifications         
def load_encrypted_password():
    with open("encryption/secret.key", "rb") as key_file:
        key = key_file.read()

    with open("encryption/email_password.enc", "rb") as enc_file:
        encrypted = enc_file.read()

    fernet = Fernet(key)
    return fernet.decrypt(encrypted).decode()