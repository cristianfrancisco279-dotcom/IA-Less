import sys
print("python:", sys.version)
try:
    import openai
    print("openai:", getattr(openai, "__version__", "?"))
except Exception as e:
    print("openai import error:", e)
try:
    import groq
    print("groq: ok")
except Exception as e:
    print("groq import error:", e)
try:
    import google.generativeai as genai
    print("gemini: ok")
except Exception as e:
    print("gemini import error:", e)
