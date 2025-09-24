import os
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from openai import OpenAI, APIError

# Load environment variables from .env file
load_dotenv()

# --- OpenAI Client Initialization ---
# Point the client to the OpenRouter API
open_router_api_key = os.environ.get('OPENROUTER_API_KEY')
if not open_router_api_key:
    # This is a fatal error for the server, so we log it and exit if the key is not set.
    logging.critical("CRITICAL: OPENROUTER_API_KEY environment variable not set.")
    exit("OPENROUTER_API_KEY is not set. The application cannot start.")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=open_router_api_key,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# We specify the 'public' directory as the static folder and serve it at the root
app = Flask(__name__, static_folder='public', static_url_path='')

@app.route('/')
def index():
    # Serve the index.html file from the static folder
    return app.send_static_file('index.html')

@app.route('/api/generate-concept', methods=['POST'])
def generate_concept():
    try:
        data = request.get_json()

        # Extract data from the frontend request
        user_card_name = data.get('cardName', '')
        card_type = data.get('cardType', 'Any')
        sub_type_detail = data.get('subTypeDetail', '')
        description = data.get('description', '')
        rarity = data.get('rarity', 'Common')

        card_concept_prompt = f"""You are a card game designer. Create a detailed card based on:
- Card Name: "{user_card_name or "Auto-generate"}"
- Type: "{card_type}"
{f'- {sub_type_detail}' if sub_type_detail else ''}
- Rarity: "{rarity}"
- Description: "{description}"

The rarity should influence the power of the stats and the epicness of the lore and ability. For example, Legendary cards should have higher stats (e.g., 8-10) and more powerful abilities than Common cards (e.g., 1-3).

Return ONLY a JSON object with these exact fields:
{{
    "cardName": "Cool name (max 25 chars)",
    "cardLore": "Brief lore (max 120 chars)",
    "diceRoll": "number_between_0_and_12",
    "stats": {{
        "attack": "number_between_01_and_10",
        "defense": "number_between_01_and_10",
        "speed": "number_between_01_and_10"
    }},
    "abilityKeyword": "A short keyword for the ability (e.g., Flying, Taunt, Ambush). Max 15 chars.",
    "triggeredAbility": "Rules text for an ability, like 'When this card enters the battlefield, draw a card.' (max 150 chars)",
    "imagePrompt": "A detailed, artistic description for an image generator (max 250 chars). This should be a visually rich description of the card's subject."
}}

The card name must be in title case."""

        chat_completion = client.chat.completions.create(
            model="deepseek/deepseek-chat-v3.1:free",
            messages=[{"role": "user", "content": card_concept_prompt}],
            response_format={"type": "json_object"}
        )

        # The openai library returns a pydantic model, we need to convert it to a dict to jsonify
        return jsonify(chat_completion.model_dump())

    except APIError as e:
        logging.error(f"OpenRouter API Error: {e.status_code} - {e.response}")
        return jsonify({'error': f'Failed to communicate with OpenRouter API: {e.message}'}), e.status_code or 502
    except Exception as e:
        logging.error(f"An unexpected error occurred in concept generation: {e}")
        return jsonify({'error': 'An unexpected server error occurred during concept generation.'}), 500

@app.route('/api/generate-text', methods=['POST'])
def generate_text():
    try:
        data = request.get_json()
        prompt = data.get('prompt')

        if not prompt:
            return jsonify({'error': 'Missing prompt'}), 400

        chat_completion = client.chat.completions.create(
            model="deepseek/deepseek-chat-v3.1:free",
            messages=[{"role": "user", "content": prompt}]
        )

        return jsonify(chat_completion.model_dump())

    except APIError as e:
        logging.error(f"OpenRouter API Error for text generation: {e.status_code} - {e.response}")
        return jsonify({'error': f'Failed to communicate with OpenRouter API: {e.message}'}), e.status_code or 502
    except Exception as e:
        logging.error(f"An unexpected error occurred in text generation: {e}")
        return jsonify({'error': 'An unexpected server error occurred during text generation.'}), 500

@app.route('/api/generate-image', methods=['POST'])
def generate_image():
    try:
        data = request.get_json()
        model = data.get('model')
        prompt = data.get('prompt')

        if not model or not prompt:
            return jsonify({'error': 'Missing model or prompt'}), 400

        # The OpenAI library is the standard way to interact with OpenAI-compatible APIs like OpenRouter.
        # It handles the request formatting for us.
        image_response = client.images.generate(
            model=model,
            prompt=prompt,
            n=1,
            size="1024x1024" # Using a fixed size for simplicity, as the card layout is square.
        )

        image_url = image_response.data[0].url
        if not image_url:
            raise Exception("Image URL not found in OpenRouter response")

        # The frontend expects a 'data' key with a list containing an object with a 'url' key.
        # The client.images.generate response is already in this format.
        return jsonify(image_response.model_dump())

    except APIError as e:
        logging.error(f"OpenRouter API Error for image generation: {e.status_code} - {e.response}")
        # Pass through the status code from the API if available, otherwise default to 502
        return jsonify({'error': f'Image generation failed: {e.message}'}), e.status_code or 502
    except Exception as e:
        logging.error(f"An unexpected error occurred in image generation: {e}")
        return jsonify({'error': 'An unexpected server error occurred during image generation.'}), 500

if __name__ == '__main__':
    # Use the PORT environment variable if available, otherwise default to 3000
    port = int(os.environ.get('PORT', 3000))
    # Listen on all network interfaces.
    # The reloader has to be disabled because it will not work in this environment.
    app.run(host='0.0.0.0', port=port, debug=False)
