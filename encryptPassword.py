from cryptography.fernet import Fernet
import os

def createEncryptionKey():
    KEY_PATH = "secret.key"
    
    if os.path.exists(KEY_PATH):
        print(f"{KEY_PATH} already exists. Delete it manually if you want to regenerate the key.")
        exit(1)
    key = Fernet.generate_key()
    with open("secret.key", "wb") as f:
        f.write(key)

    print("Secret key generated and saved to secret.key")


def encryptPassword():
    ENC_PATH = "email_password.enc"
    
    # Check for existing encrypted password
    if os.path.exists(ENC_PATH):
        print(f"{ENC_PATH} already exists. Delete it manually if you want to re-encrypt a new password.")
        exit(1)
    # Load your encryption key
    with open("secret.key", "rb") as f:
        key = f.read()

    fernet = Fernet(key)

    # Encrypt your email password
    raw_password = input("Enter the password you want to encrypt: ").strip()
    encrypted = fernet.encrypt(raw_password.encode())

    with open("email_password.enc", "wb") as f:
        f.write(encrypted)

    print("Encrypted password saved to email_password.enc")

if __name__ == "__main__":
    encryptPassword()