import os
import sys
from google import genai

def probar_nueva_api_interactions():
    # Inicializa el cliente oficial actualizado
    client = genai.Client()
    
    print("🐳 [Docker] Iniciando turno usando la nueva API de Interactions...")
    
    try:
        # La nueva forma recomendada por Google usando la familia 3.5
        interaction = client.interactions.create(
            model='gemini-3.5-flash',
            input='Hola Gemini, confírmame si respondes desde la nueva Interactions API para mi app.'
        )
        
        print("\n--- Respuesta Exitosa (Interactions API) ---")
        # Accedemos mediante la propiedad directa que consolida el texto
        print(interaction.output_text)
        print("--------------------------------------------")
        
    except Exception as e:
        print(f"\n❌ Error en la solicitud de Interactions: {e}", file=sys.stderr)

if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ Error: La variable GEMINI_API_KEY no está configurada.", file=sys.stderr)
    else:
        probar_nueva_api_interactions()