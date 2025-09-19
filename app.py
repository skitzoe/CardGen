import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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

        open_router_api_key = os.environ.get('OPENROUTER_API_KEY')
        if not open_router_api_key:
            return jsonify({'error': 'OPENROUTER_API_KEY not set on the server'}), 500

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

        headers = {
            "Authorization": f"Bearer {open_router_api_key}",
            "Content-Type": "application/json",
        }

        referer = os.environ.get('OPENROUTER_REFERER')
        if referer:
            headers["HTTP-Referer"] = referer

        title = os.environ.get('OPENROUTER_TITLE')
        if title:
            headers["X-Title"] = title

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json={
                "model": "deepseek/deepseek-chat-v3.1:free",
                "messages": [{"role": "user", "content": card_concept_prompt}],
                "response_format": {"type": "json_object"}
            }
        )

        response.raise_for_status()
        return jsonify(response.json())

    except requests.exceptions.RequestException as e:
        # It's good practice to log the error
        print(f"Error calling OpenRouter API: {e}")
        return jsonify({'error': f'Failed to communicate with OpenRouter API: {e}'}), 502
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return jsonify({'error': 'An unexpected error occurred on the server.'}), 500

@app.route('/api/generate-image', methods=['POST'])
def generate_image():
    try:
        data = request.get_json()
        model = data.get('model')
        prompt = data.get('prompt')

        if not model or not prompt:
            return jsonify({'error': 'Missing model or prompt'}), 400

        if model.startswith('deepai-'):
            api_key = os.environ.get('DEEPAI_API_KEY')
            if not api_key:
                return jsonify({'error': 'DEEPAI_API_KEY not set on the server'}), 500

            deepai_model_name = model.replace('deepai-', '')
            api_url = f'https://api.deepai.org/api/{deepai_model_name}'
            if deepai_model_name in ['stable-diffusion', 'fantasy-world']:
                 api_url = 'https://api.deepai.org/api/text2img'

            response = requests.post(
                api_url,
                data={'text': prompt},
                headers={'api-key': api_key}
            )
            response.raise_for_status()
            return jsonify(response.json())

        elif model.startswith('stabilityai/') or model.startswith('custom_backend'): # Assuming openrouter for stabilityai models
            # Handle OpenRouter and Custom Backend
            if model == 'custom_backend':
                # Custom backend logic
                custom_backend_url = data.get('customBackendUrl')
                if not custom_backend_url:
                    return jsonify({'error': 'Custom backend URL not provided'}), 400

                response = requests.post(
                    custom_backend_url,
                    json={'prompt': prompt},
                    headers={'Content-Type': 'application/json'}
                )
                # Custom backends might return image data directly
                # For simplicity, we assume it returns a JSON with a URL like the others
                # A more robust solution might handle raw image data
                response.raise_for_status()
                # Assuming the custom backend returns a blob, we can't easily proxy that
                # without more complex handling. A simple URL proxy is more feasible.
                # Let's assume for now the custom backend returns a JSON with an `output_url`.
                return jsonify(response.json())

            else: # OpenRouter
                api_key = os.environ.get('OPENROUTER_API_KEY')
                if not api_key:
                    return jsonify({'error': 'OPENROUTER_API_KEY not set on the server'}), 500

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }

                referer = os.environ.get('OPENROUTER_REFERER')
                if referer:
                    headers["HTTP-Referer"] = referer

                title = os.environ.get('OPENROUTER_TITLE')
                if title:
                    headers["X-Title"] = title

                response = requests.post(
                    "https://openrouter.ai/api/v1/images/generations",
                    headers=headers,
                    json={
                        "model": model,
                        "prompt": prompt,
                        "n": 1,
                        "size": "1024x1024"
                    }
                )
                response.raise_for_status()
                return jsonify(response.json())
        else:
            return jsonify({'error': f'Unsupported image model: {model}'}), 400

    except requests.exceptions.RequestException as e:
        print(f"Error calling Image Generation API: {e}")
        return jsonify({'error': f'Failed to communicate with Image API: {e}'}), 502
    except Exception as e:
        print(f"An unexpected error occurred in image generation: {e}")
        return jsonify({'error': 'An unexpected server error occurred during image generation.'}), 500

# Flask will automatically handle serving other files from the static folder.
# For example, if you had a style.css, a request to /style.css would work.

if __name__ == '__main__':
    # Use the PORT environment variable if available, otherwise default to 3000
    port = int(os.environ.get('PORT', 3000))
    # Listen on all network interfaces.
    # The reloader has to be disabled because it will not work in this environment.
    app.run(host='0.0.0.0', port=port, debug=False)
