# app.py
from flask import Flask, request, Response, send_file
from openai import OpenAI
import requests
import os
import uuid
import tempfile

# Inicializar Flask
app = Flask(__name__)

# Inicializar cliente OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Credenciales Twilio (se toman de variables de entorno)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")


@app.route("/")
def home():
    return "🤖 AI Callbot corriendo correctamente."


# --------------------------------------------------------------------
# FASE 1: Twilio llama aquí cuando entra una llamada
# --------------------------------------------------------------------
@app.route("/voice", methods=["POST"])
def voice():
    print("📞 Nueva llamada recibida")

    # Twilio responderá con estas instrucciones
    # Pide al usuario hablar y deja un mensaje grabado
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="es-ES">Hola, por favor deja tu mensaje después del tono. Cuando termines, cuelga o espera.</Say>
    <Record 
        action="/recording" 
        method="POST" 
        maxLength="20"
        finishOnKey="*" 
        playBeep="true" />
</Response>"""

    return Response(twiml, mimetype="text/xml")


# --------------------------------------------------------------------
# FASE 2: Twilio llama aquí cuando termina de grabar al usuario
# --------------------------------------------------------------------
@app.route("/recording", methods=["POST"])
def recording():
    call_id = str(uuid.uuid4())
    recording_url = request.form.get("RecordingUrl")

    if not recording_url:
        print(f"❌ [{call_id}] No se recibió RecordingUrl")
        return Response("""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="es-ES">Lo siento, no pude recibir tu grabación.</Say>
</Response>""", mimetype="text/xml")

    print(f"🎙️ [{call_id}] Grabación recibida: {recording_url}")

    # ----------------------------------------------------------------
    # 1️⃣ Descargar la grabación
    # ----------------------------------------------------------------
    audio = requests.get(recording_url + ".wav", auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
    input_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.wav', delete=False)
    input_file.write(audio.content)
    input_file.close()
    print(f"✅ [{call_id}] Grabación descargada correctamente")

    # ----------------------------------------------------------------
    # 2️⃣ Transcribir con Whisper
    # ----------------------------------------------------------------
    print(f"🎤 [{call_id}] Transcribiendo audio...")
    with open(input_file.name, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )
    texto_usuario = transcript.text.strip()
    print(f"👤 [{call_id}] Usuario: {texto_usuario}")

    # ----------------------------------------------------------------
    # 3️⃣ Generar respuesta con GPT
    # ----------------------------------------------------------------
    print(f"🤖 [{call_id}] Generando respuesta con ChatGPT...")
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Eres un asesor inmobiliario amable, servicial y empático. Responde de forma natural, como si estuvieras hablando con el usuario."},
            {"role": "user", "content": texto_usuario}
        ]
    )
    texto_respuesta = completion.choices[0].message.content or "Lo siento, no pude generar una respuesta."
    print(f"💬 [{call_id}] ChatGPT: {texto_respuesta}")

    # ----------------------------------------------------------------
    # 4️⃣ Convertir texto → voz con TTS
    # ----------------------------------------------------------------
    print(f"🔊 [{call_id}] Convirtiendo texto a voz...")
    speech = client.audio.speech.create(
        model="tts-1",
        voice="alloy",
        input=texto_respuesta
    )

    output_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.mp3', delete=False)
    output_file.write(speech.content)
    output_file.close()
    print(f"✅ [{call_id}] Audio de respuesta generado")

    # ----------------------------------------------------------------
    # 5️⃣ Responder a Twilio para que reproduzca el audio
    # ----------------------------------------------------------------
    base_url = request.url_root.rstrip('/')
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{base_url}/audio/{call_id}.mp3</Play>
</Response>"""

    # Guardar la ruta temporal para servir el audio luego
    app.config[f'audio_{call_id}'] = output_file.name

    # Limpiar la grabación original
    try:
        os.unlink(input_file.name)
    except Exception as e:
        print(f"⚠️ [{call_id}] No se pudo eliminar el archivo temporal: {e}")

    return Response(twiml, mimetype="text/xml")


# --------------------------------------------------------------------
# FASE 3: Servir el archivo de audio generado
# --------------------------------------------------------------------
@app.route("/audio/<call_id>.mp3")
def serve_audio(call_id):
    file_path = app.config.get(f'audio_{call_id}')
    if not file_path or not os.path.exists(file_path):
        return "Audio no encontrado", 404

    response = send_file(file_path, mimetype="audio/mpeg")

    # Limpieza del archivo de audio después de servirlo
    try:
        os.unlink(file_path)
        del app.config[f'audio_{call_id}']
    except Exception as e:
        print(f"⚠️ [{call_id}] No se pudo eliminar el audio temporal: {e}")

    return response


# --------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
