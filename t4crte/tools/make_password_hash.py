import sys
import hashlib

def make_hash(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        pwd = sys.argv[1]
    else:
        pwd = input("أدخل كلمة المرور لحساب الـ Hash: ")
    hashed = make_hash(pwd)
    print(f"SHA-256 Hash: {hashed}")
