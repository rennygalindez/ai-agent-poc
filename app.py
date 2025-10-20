from flask import Flask, request, Response, send_file
from openai import OpenAI
import requests
import os
import uuid
import tempfile
from pathlib import Path

app = Flask(__name__)

# Initialize OpenAI client with API key from environment
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Load Twilio credentials from environment
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

@app.route("/")
def home():
    return "🤖 AI Callbot está corriendo correctamente."

@app.route("/voice", methods=["POST"])
def voice():
    call_id = str(uuid.uuid4())
    input_file = None
    output_file = None
    
    try:
        # Validate Twilio credentials are available
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
            print("❌ Error: Twilio credentials not configured")
            return Response("""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="es-ES">Error de configuración del servidor.</Say>
</Response>""", mimetype="text/xml")
        
        # 1️⃣ Get the recording URL from Twilio
        recording_url = request.form.get("RecordingUrl")
        if not recording_url:
            print("❌ Error: No RecordingUrl received from Twilio")
            return Response("""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="es-ES">Lo siento, no pude recibir tu grabación.</Say>
</Response>""", mimetype="text/xml")
        
        # Download the audio file with Twilio authentication
        recording_url = recording_url + ".wav"
        print(f"📥 [{call_id}] Downloading recording from: {recording_url}")
        audio = requests.get(recording_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        
        if audio.status_code != 200:
            print(f"❌ [{call_id}] Failed to download recording (status {audio.status_code})")
            return Response("""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="es-ES">No pude descargar la grabación.</Say>
</Response>""", mimetype="text/xml")
        
        # Create unique temporary file for this call's input
        input_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.wav', delete=False)
        input_file.write(audio.content)
        input_file.close()
        print(f"✅ [{call_id}] Recording downloaded successfully")
        
        # 2️⃣ Transcribe the voice with Whisper
        print(f"🎤 [{call_id}] Transcribing audio with Whisper...")
        with open(input_file.name, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f
            )
        texto_usuario = transcript.text
        print(f"👤 [{call_id}] Usuario: {texto_usuario}")
        
        # 3️⃣ Generate response with ChatGPT
        print(f"🤖 [{call_id}] Generating response with ChatGPT...")
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un asesor inmobiliario amable y servicial."},
                {"role": "user", "content": texto_usuario}
            ]
        )
        texto_respuesta = completion.choices[0].message.content or "Lo siento, no pude generar una respuesta."
        print(f"🤖 [{call_id}] ChatGPT: {texto_respuesta}")
        
        # 4️⃣ Convert text → voice (TTS)
        print(f"🔊 [{call_id}] Converting text to speech...")
        speech = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=texto_respuesta
        )
        
        # Save the audio response to unique file
        output_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.mp3', delete=False)
        output_file.write(speech.content)
        output_file.close()
        print(f"✅ [{call_id}] Audio response saved")
        
        # 5️⃣ Twilio plays the voice response
        # Get the base URL from the request
        base_url = request.url_root.rstrip('/')
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{base_url}/audio/{call_id}.mp3</Play>
</Response>"""
        
        # Store the output file path for serving
        app.config[f'audio_{call_id}'] = output_file.name
        
        return Response(twiml, mimetype="text/xml")
    
    except Exception as e:
        print(f"❌ [{call_id}] Error: {str(e)}")
        return Response("""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="es-ES">Lo siento, ocurrió un error procesando tu solicitud.</Say>
</Response>""", mimetype="text/xml")
    finally:
        # Clean up input file
        if input_file and os.path.exists(input_file.name):
            try:
                os.unlink(input_file.name)
            except Exception as e:
                print(f"⚠️ [{call_id}] Failed to clean up input file: {e}")

@app.route("/audio/<call_id>.mp3")
def serve_audio(call_id):
    try:
        # Get the file path for this call ID
        file_path = app.config.get(f'audio_{call_id}')
        if not file_path or not os.path.exists(file_path):
            return "Audio file not found", 404
        
        # Serve the file
        response = send_file(file_path, mimetype="audio/mpeg")
        
        # Clean up the file after serving (schedule deletion)
        try:
            os.unlink(file_path)
            del app.config[f'audio_{call_id}']
        except Exception as e:
            print(f"⚠️ [{call_id}] Failed to clean up output file: {e}")
        
        return response
    except Exception as e:
        print(f"❌ Error serving audio for {call_id}: {str(e)}")
        return "Error serving audio", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
