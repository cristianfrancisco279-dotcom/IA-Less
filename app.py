from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
import os
import uuid
import json
from datetime import datetime
from urllib.parse import urlparse
from ai import AIProvider
import requests
import xml.etree.ElementTree as ET
import threading
import time

ENV_PATH = os.path.join(os.getcwd(), ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev")

ai = AIProvider()

def system_prompt():
    return "Você é Less, um assistente educado, amigável e claro. Responda em português. Explique conteúdos de forma simples e objetiva. Ajude em estudos, tecnologia, tarefas básicas e orientações gerais. Mantenha uma conversa natural e confiável."

DATA_DIR = os.path.join(os.getcwd(), "data", "chats")
os.makedirs(DATA_DIR, exist_ok=True)

def _chat_path(cid):
    return os.path.join(DATA_DIR, f"{cid}.json")

def _save_chat(cid, messages):
    title = ""
    for m in messages:
        if m.get("role") == "user":
            title = (m.get("content") or "")[:60]
            break
    meta = {
        "id": cid,
        "title": title or "Nova conversa",
        "created_at": session.get("created_at") or datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "messages": messages
    }
    with open(_chat_path(cid), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

@app.route("/", strict_slashes=False)
def home():
    return render_template("index.html")

@app.route("/status", strict_slashes=False)
def status():
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    has_groq = bool(os.getenv("GROQ_API_KEY"))
    return jsonify({
        "provider": ai.provider,
        "model": ai.model,
        "ready": ai.ready,
        "env": {
            "has_openai_key": has_openai,
            "has_gemini_key": has_gemini,
            "has_groq_key": has_groq
        }
    })

@app.route("/status-ui", strict_slashes=False)
def status_ui():
    return render_template("status.html")

@app.route("/chat/new", methods=["POST"], strict_slashes=False)
def chat_new():
    cid = str(uuid.uuid4())
    session["chat_id"] = cid
    session["created_at"] = datetime.utcnow().isoformat()
    session["history"] = [{"role": "system", "content": system_prompt()}]
    _save_chat(cid, session["history"])
    return jsonify({"chat_id": cid})

@app.route("/chat/list", methods=["GET"], strict_slashes=False)
def chat_list():
    items = []
    for name in os.listdir(DATA_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(DATA_DIR, name), "r", encoding="utf-8") as f:
                x = json.load(f)
            items.append({
                "id": x.get("id"),
                "title": x.get("title"),
                "updated_at": x.get("updated_at")
            })
        except:
            pass
    items.sort(key=lambda k: k.get("updated_at") or "", reverse=True)
    return jsonify({"chats": items})

@app.route("/chat/load/<cid>", methods=["GET"], strict_slashes=False)
def chat_load(cid):
    p = _chat_path(cid)
    if not os.path.exists(p):
        return jsonify({"erro": "Chat não encontrado"}), 404
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    session["chat_id"] = cid
    session["created_at"] = data.get("created_at") or datetime.utcnow().isoformat()
    session["history"] = data.get("messages") or [{"role": "system", "content": system_prompt()}]
    return jsonify({"messages": session["history"], "chat_id": cid, "title": data.get("title")})

def _parse_rss(url, limit=8):
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        if not r.ok:
            return []
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title and link:
                items.append({"title": title, "link": link})
            if len(items) >= limit:
                break
        if not items:
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                link = (link_el.get("href") if link_el is not None else "") or ""
                if title and link:
                    items.append({"title": title, "link": link})
                if len(items) >= limit:
                    break
        return items
    except:
        return []

TOPICS = {
    "general": [
        "https://news.google.com/rss?hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://rss.cnn.com/rss/edition.rss",
        "https://feeds.reuters.com/reuters/worldNews"
    ],
    "tech": [
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://www.theverge.com/rss/index.xml",
        "https://www.wired.com/feed/rss"
    ],
    "games": [
        "https://www.gamespot.com/feeds/game-news/",
        "https://kotaku.com/rss",
        "https://www.eurogamer.net/feed/news",
        "https://www.pcgamer.com/rss/"
    ]
}

NEWS_CACHE = {"general": [], "tech": [], "games": [], "updated_at": None}
NEWS_INTERVAL_SEC = 120

def _fetch_topic(topic):
    urls = TOPICS.get(topic) or TOPICS["general"]
    merged = []
    for u in urls:
        merged.extend(_parse_rss(u, limit=8))
    return merged[:16]

def _refresh_news():
    while True:
        try:
            NEWS_CACHE["general"] = _fetch_topic("general")
            NEWS_CACHE["tech"] = _fetch_topic("tech")
            NEWS_CACHE["games"] = _fetch_topic("games")
            NEWS_CACHE["updated_at"] = datetime.utcnow().isoformat()
        except:
            pass
        time.sleep(NEWS_INTERVAL_SEC)

STARTED_NEWS = False
def _start_news_thread():
    global STARTED_NEWS
    if STARTED_NEWS:
        return
    t = threading.Thread(target=_refresh_news, daemon=True)
    t.start()
    STARTED_NEWS = True
@app.before_request
def _ensure_news_thread():
    _start_news_thread()

@app.route("/news/latest", methods=["GET"], strict_slashes=False)
def news_latest():
    topic = (request.args.get("topic") or "general").lower()
    if topic not in ("general","tech","games"):
        topic = "general"
    return jsonify({"topic": topic, "items": NEWS_CACHE.get(topic) or [], "updated_at": NEWS_CACHE.get("updated_at")})

@app.route("/responder", methods=["GET", "POST"], strict_slashes=False)
def responder():
    if request.method == "GET":
        return jsonify({"message": "Use POST com { mensagem: ... }"}), 200
    dados = request.get_json() or {}
    mensagem = (dados.get("mensagem") or "").strip()
    low = mensagem.lower()
    def pick_topic(t):
        t = t.lower()
        if any(s in t for s in ["jogo","games","videogame"]):
            return "games"
        if any(s in t for s in ["tech","tecnolog","software","programa"]):
            return "tech"
        return "general"
    if any(k in low for k in ["notícia","noticias","noticia","news"]):
        topic = pick_topic(low)
        urls = TOPICS.get(topic) or TOPICS["general"]
        merged = []
        for u in urls:
            merged.extend(_parse_rss(u, limit=4))
        def host_name(link):
            h = urlparse(link).netloc.lower()
            if "google" in h: return "Google News"
            if "bbc" in h: return "BBC"
            if "cnn" in h: return "CNN"
            if "reuters" in h: return "Reuters"
            if "uol" in h: return "UOL"
            parts = h.split(".")
            base = parts[-2] if len(parts)>=2 else h
            return base.capitalize()
        def br_date(d):
            meses = ["janeiro","fevereiro","março","abril","maio","junho","julho","agosto","setembro","outubro","novembro","dezembro"]
            return f"{d.day:02d} de {meses[d.month-1]} de {d.year}"
        hoje = br_date(datetime.utcnow())
        def cat(title):
            t = title.lower()
            econ_kw = ["ação","ações","bolsa","mercado","índice","sp500","s&p","lucro","resultado","guidance","economia","inflação","criptomoeda","bitcoin","ethereum","xrp","btc","eth"]
            world_kw = ["tiroteio","explosão","acidente","conflito","guerra","governo","eleição","canadá","eua","rein o unido","china","russia","mundo"]
            if any(k in t for k in econ_kw): return "economy"
            if any(k in t for k in world_kw): return "world"
            return "other"
        tops = merged[:8]
        economy = [it for it in merged if cat(it["title"])=="economy"][:4]
        world = [it for it in merged if cat(it["title"])=="world"][:4]
        others = [it for it in merged if cat(it["title"])=="other"][:4]
        txt = []
        txt.append(f"Estas são as principais notícias de hoje ({hoje}) — cobrindo Brasil e mundo 🌎:")
        txt.append("")
        txt.append(f"Principais Notícias de Hoje – {hoje}")
        for it in tops:
            src = host_name(it["link"])
            txt.append(f"{src}")
            txt.append(f"{it['title']}")
            txt.append(f"hoje")
        if economy:
            txt.append("")
            txt.append("🗞️ Economia e mercados")
            for it in economy:
                txt.append(f"- {it['title']} – {it['link']}")
        if world:
            txt.append("")
            txt.append("🌍 Mundo")
            for it in world:
                txt.append(f"- {it['title']} – {it['link']}")
        if others:
            txt.append("")
            txt.append("📊 Destaques adicionais")
            for it in others:
                txt.append(f"- {it['title']} – {it['link']}")
        txt.append("")
        txt.append("Se quiser, posso detalhar cada notícia ou separar por categoria (Brasil, internacional, economia, esportes etc.). É só me dizer 🙂")
        resposta = "\n".join(txt) or "Sem itens no momento."
        history = session.get("history", [])
        if not history or history[0].get("role") != "system":
            history = [{"role": "system", "content": system_prompt()}] + history
        if mensagem:
            history.append({"role": "user", "content": mensagem})
        history.append({"role": "assistant", "content": resposta})
        session["history"] = history[-16:]
        cid = session.get("chat_id") or str(uuid.uuid4())
        session["chat_id"] = cid
        if not session.get("created_at"):
            session["created_at"] = datetime.utcnow().isoformat()
        _save_chat(cid, session["history"])
        return jsonify({"resposta": resposta, "chat_id": cid})
    history = session.get("history", [])
    if not history or history[0].get("role") != "system":
        history = [{"role": "system", "content": system_prompt()}] + history
    if mensagem:
        history.append({"role": "user", "content": mensagem})
        history.append({"role": "user", "content": mensagem})
    try:
        resposta = ai.respond(history)
    except Exception as e:
        return jsonify({"erro": "Falha ao gerar resposta", "detalhe": str(e)}), 500
    history.append({"role": "assistant", "content": resposta})
    session["history"] = history[-16:]
    cid = session.get("chat_id") or str(uuid.uuid4())
    session["chat_id"] = cid
    if not session.get("created_at"):
        session["created_at"] = datetime.utcnow().isoformat()
    _save_chat(cid, session["history"])
    return jsonify({"resposta": resposta, "chat_id": cid})

@app.errorhandler(404)
def not_found(e):
    return redirect(url_for("home"))

@app.route("/health", methods=["GET"], strict_slashes=False)
def health():
    return jsonify({"ok": True, "updated_at": NEWS_CACHE.get("updated_at")}), 200

if __name__ == "__main__":
    _start_news_thread()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
