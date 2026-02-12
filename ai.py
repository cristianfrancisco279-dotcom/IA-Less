import os
import importlib
import requests
from dotenv import load_dotenv
ENV_PATH = os.path.join(os.getcwd(), ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)

class AIProvider:
    def __init__(self):
        openai_key = os.getenv("OPENAI_API_KEY")
        groq_key = os.getenv("GROQ_API_KEY")
        env_provider = (os.getenv("AI_PROVIDER") or "").lower()
        self.provider = env_provider or ("openai" if openai_key else ("groq" if groq_key else "openai"))
        self.model = os.getenv("AI_MODEL")
        self.client = None
        self.ready = False
        if self.provider == "openai":
            from openai import OpenAI
            key = openai_key
            self.client = OpenAI(api_key=key) if key else None
            self.model = self.model or "gpt-4o-mini"
            self.ready = self.client is not None
        elif self.provider == "gemini":
            genai = importlib.import_module("google.generativeai")
            key = os.getenv("GEMINI_API_KEY")
            if key:
                genai.configure(api_key=key)
                self.genai = genai
                self.model = self.model or "gemini-1.5-flash"
                self.ready = True
        elif self.provider == "groq":
            key = groq_key
            self.session = requests.Session() if key else None
            if self.session:
                self.session.headers.update({"Authorization": f"Bearer {key}","Content-Type":"application/json"})
            self.model = self.model or self._pick_groq_model()
            self.ready = self.session is not None

    def respond(self, messages):
        if not self.ready:
            return "Configure o provedor e a chave da API para ativar a IA."
        if self.provider == "openai":
            chat_messages = []
            for m in messages:
                role = m.get("role") or "user"
                if role not in ("system","user","assistant"):
                    role = "user"
                chat_messages.append({"role": role, "content": m.get("content","")})
            r = self.client.chat.completions.create(model=self.model, messages=chat_messages)
            return r.choices[0].message.content
        if self.provider == "groq":
            payload={"model":self.model,"messages":[{"role":m.get("role","user"),"content":m.get("content","")} for m in messages]}
            url="https://api.groq.com/openai/v1/chat/completions"
            resp=self.session.post(url,json=payload,timeout=30)
            if not resp.ok:
                txt=resp.text
                if resp.status_code==401:
                    return "A IA está indisponível. Verifique GROQ_API_KEY e AI_PROVIDER=groq."
                if resp.status_code in (400,404) and ("model_decommissioned" in txt or "model_not_found" in txt):
                    self.model=self._pick_groq_model()
                    payload["model"]=self.model
                    resp=self.session.post(url,json=payload,timeout=30)
                    if not resp.ok:
                        if resp.status_code==401:
                            return "A IA está indisponível. Verifique GROQ_API_KEY e AI_PROVIDER=groq."
                        raise Exception(f"{resp.status_code}: {resp.text}")
                else:
                    raise Exception(f"{resp.status_code}: {txt}")
            data=resp.json()
            return data["choices"][0]["message"]["content"]
        if self.provider == "gemini":
            modelo = self.genai.GenerativeModel(self.model)
            prompt = "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in messages)
            r = modelo.generate_content(prompt)
            return getattr(r, "text", None) or "Sem resposta da IA."
        return "Provedor de IA inválido."

    def _pick_groq_model(self):
        try:
            r=self.session.get("https://api.groq.com/openai/v1/models",timeout=15)
            if not r.ok:
                return "mixtral-8x7b-32768"
            ids=[m.get("id") for m in r.json().get("data",[])]
            prefs=["llama-3.1-8b-instant","llama-3.1-70b-instruct","mixtral-8x7b-32768","gemma2-9b-it"]
            for p in prefs:
                if p in ids:
                    return p
            return ids[0] if ids else "mixtral-8x7b-32768"
        except:
            return "mixtral-8x7b-32768"
