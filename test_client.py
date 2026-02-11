import json
import requests

def main():
    status = requests.get("http://127.0.0.1:5000/status", timeout=10).json()
    print("STATUS:", json.dumps(status, ensure_ascii=False))
    url = "http://127.0.0.1:5000/responder"
    payload = {"mensagem": "Quais sao as noticias de hoje?"}
    try:
        r = requests.post(url, json=payload, timeout=30)
        print("HTTP:", r.status_code)
        ct = r.headers.get("Content-Type", "")
        if "application/json" in ct:
            print("RESPOSTA:", json.dumps(r.json(), ensure_ascii=False))
        else:
            print("RESPOSTA (texto):", r.text[:500])
    except Exception as e:
        print("ERRO:", repr(e))

if __name__ == "__main__":
    main()
