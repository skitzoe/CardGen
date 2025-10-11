import os
import logging
import requests
import json
import time
from flask import Flask, request, jsonify
import base64
import uuid
from functools import wraps
from dotenv import load_dotenv
from openai import OpenAI, APIError
from firebase_config import initialize_firebase
from firebase_admin import db, storage, auth


# Load environment variables from .env file
load_dotenv()

# --- Global State ---
firebase_initialized = False

# Initialize Firebase
firebase_initialized = initialize_firebase()
if not firebase_initialized:
    logging.critical("CRITICAL: Firebase initialization failed. The app will run in a degraded state.")

# --- API Key and Client Initialization ---
open_router_api_key = os.environ.get('OPENROUTER_API_KEY')
deepai_api_key = os.environ.get('DEEPAI_API_KEY')
dreamstudio_api_key = os.environ.get('DREAMSTUDIO_API_KEY')

if not open_router_api_key:
    logging.warning("Warning: OPENROUTER_API_KEY environment variable not set. OpenRouter models will not be available.")

# Point the OpenAI client to the OpenRouter API
client = None
if open_router_api_key:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=open_router_api_key,
    )

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Subclass Flask to set a default charset for JSON responses
class CustomFlask(Flask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.json.ensure_ascii = False

# We specify the 'public' directory as the static folder and serve it at the root
app = CustomFlask(__name__, static_folder='public', static_url_path='')

# --- Authentication Decorator ---
def protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if Firebase is available before proceeding with protected routes
        if not firebase_initialized:
            logging.warning("Attempted to access a protected route while Firebase is not initialized.")
            return jsonify({'error': 'The server is not connected to the database. Please contact the administrator.'}), 503

        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token is missing or invalid.'}), 401

        id_token = auth_header.split('Bearer ')[1]
        try:
            decoded_token = auth.verify_id_token(id_token)
        except auth.InvalidIdTokenError:
            return jsonify({'error': 'Invalid authentication token.'}), 403
        except auth.ExpiredIdTokenError:
            return jsonify({'error': 'Authentication token has expired.'}), 403
        except Exception as e:
            logging.error(f"Token verification failed: {e}")
            return jsonify({'error': 'Could not verify authentication token.'}), 401
        return f(decoded_token, *args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    # If Firebase isn't working, we can still try to serve the page,
    # but the frontend will likely fail on API calls.
    if not firebase_initialized:
        logging.warning("Serving index.html, but Firebase is not initialized. Frontend functionality will be limited.")
    # Serve the index.html file from the static folder
    return app.send_static_file('index.html')

@app.route('/gallery')
def gallery():
    """Serves the gallery.html page."""
    # Serve the gallery.html file from the static folder
    return app.send_static_file('gallery.html')

@app.route('/game')
def game():
    """Serves the game.html page."""
    # Serve the game.html file from the static folder
    return app.send_static_file('game.html')

@app.route('/api/firebase-config')
def firebase_config():
    """Provides the necessary Firebase config to the frontend."""
    # These keys are safe to expose to the client.
    # They are required for the Firebase JS SDK to connect to your project.
    required_vars = {
        "apiKey": "FIREBASE_API_KEY",
        "authDomain": "FIREBASE_AUTH_DOMAIN",
        "databaseURL": "FIREBASE_DATABASE_URL",
        "projectId": "FIREBASE_PROJECT_ID",
        "storageBucket": "FIREBASE_STORAGE_BUCKET",
        "messagingSenderId": "FIREBASE_MESSAGING_SENDER_ID",
        "appId": "FIREBASE_APP_ID"
    }
    
    config = {}
    missing_vars = []
    for key, var_name in required_vars.items():
        value = os.environ.get(var_name)
        config[key] = value
        if not value:
            missing_vars.append(var_name)

    if missing_vars:
        error_message = f"Firebase configuration is incomplete on the server. Missing environment variables: {', '.join(missing_vars)}"
        logging.error(error_message)
        return jsonify({"error": error_message}), 500

    return jsonify(config)

@app.route('/api/generate-concept', methods=['POST'])
def generate_concept():
    if not firebase_initialized:
        logging.error("Attempted to generate concept while Firebase is not initialized.")
        return jsonify({'error': 'The server is not connected to the database. Please contact the administrator.'}), 503

    if not client:
        return jsonify({'error': 'The server is not configured with an OpenRouter API key.'}), 503

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
    "cardLore": "Brief lore (max 100 chars)",
    "diceRoll": "number_between_0_and_12",
    "stats": {{
        "attack": "number_between_01_and_10",
        "defense": "number_between_01_and_10",
        "speed": "number_between_01_and_10"
    }},
    "abilityKeyword": "A short keyword for the ability (e.g., Flying, Taunt, Ambush). Max 20 chars.",
    "triggeredAbility": "Rules text for an ability, like 'When this card enters the battlefield, draw a card.' (max 120 chars)",
    "imagePrompt": "A detailed, artistic description for an image generator (max 250 chars). This should be a visually rich description of the card's subject."
}}

The card name must be in title case."""

        chat_completion = client.chat.completions.create(
            model="nvidia/nemotron-nano-9b-v2:free", # Switched to a model known for good JSON mode support
            messages=[{"role": "user", "content": card_concept_prompt}]
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
    if not firebase_initialized:
        logging.error("Attempted to generate text while Firebase is not initialized.")
        return jsonify({'error': 'The server is not connected to the database. Please contact the administrator.'}), 503

    if not client:
        return jsonify({'error': 'The server is not configured with an OpenRouter API key.'}), 503

    try:
        data = request.get_json()
        prompt = data.get('prompt')

        if not prompt:
            return jsonify({'error': 'Missing prompt'}), 400

        chat_completion = client.chat.completions.create(
            model="nvidia/nemotron-nano-9b-v2:free",
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
    if not firebase_initialized:
        logging.error("Attempted to generate image while Firebase is not initialized.")
        return jsonify({'error': 'The server is not connected to the database. Please contact the administrator.'}), 503

    if not client and not deepai_api_key and not dreamstudio_api_key:
        return jsonify({'error': 'The server is not configured with any image generation API keys.'}), 503

    try:
        data = request.get_json()
        model = data.get('model')
        prompt = data.get('prompt')
        negative_prompt = data.get('negative_prompt')
        image_base64 = data.get('image') # Get the base64 image string

        if not model or not prompt:
            return jsonify({'error': 'Missing model or prompt'}), 400

        if model == 'deepai':
            if not deepai_api_key:
                return jsonify({'error': 'The DEEPAI_API_KEY is not configured on the server.'}), 503

            form_data = {'text': (None, prompt)}
            if negative_prompt:
                form_data['negative_prompt'] = (None, negative_prompt)

            response = requests.post(
                "https://api.deepai.org/api/text2img",
                # The DeepAI API expects multipart/form-data, which is achieved by using
                # the 'files' parameter in requests, even for text fields.
                # Using 'data' sends it as x-www-form-urlencoded, which causes a 401 error.
                files=form_data,
                headers={'api-key': deepai_api_key},
            )
            response.raise_for_status()
            deepai_data = response.json()
            image_url = deepai_data.get('output_url')

            if not image_url:
                raise Exception("Image URL not found in DeepAI response")

            # Transform the response to match the structure of the other APIs
            response_data = {
                "created": deepai_data.get("id", int(time.time())),
                "data": [{"url": image_url}]
            }
            return jsonify(response_data)

        elif model == 'dreamstudio':
            if not dreamstudio_api_key:
                return jsonify({'error': 'The DREAMSTUDIO_API_KEY is not configured on the server.'}), 503

            # Use a recommended engine for general purpose generation
            engine_id = "stable-diffusion-xl-1024-v1-0"
            api_host = os.environ.get("API_HOST", "https://api.stability.ai")

            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {dreamstudio_api_key}"
            }

            payload = {
                "text_prompts": [{"text": prompt, "weight": 0.5}], # Weight prompt less when using an image
                "cfg_scale": 7,
                "height": 1024,
                "width": 1024,
                "samples": 1,
                "steps": 30,
            }

            if image_base64:
                # --- Image-to-Image Logic ---
                url = f"{api_host}/v1/generation/{engine_id}/image-to-image"
                
                # Stability AI API requires the base64 string without the data URI prefix
                image_content = base64.b64decode(image_base64.split(',')[1])
                
                # Adjust payload for image-to-image
                payload['image_strength'] = 0.35
                payload['steps'] = 40 # More steps can be better for img2img
                if negative_prompt:
                    payload["text_prompts"].append({"text": negative_prompt, "weight": -1.0})

                # Prepare multipart form data
                form_data = {
                    'init_image': ('init_image.png', image_content, 'image/png'),
                    'options': (None, json.dumps(payload))
                }
                response = requests.post(url, headers=headers, files=form_data)
            else:
                # --- Text-to-Image Logic ---
                url = f"{api_host}/v1/generation/{engine_id}/text-to-image"
                headers["Content-Type"] = "application/json"
                if negative_prompt:
                    payload["text_prompts"].append({"text": negative_prompt, "weight": -1.0})
                response = requests.post(url, headers=headers, json=payload)

            response.raise_for_status()
            
            response_json = response.json()
            base64_image = response_json["artifacts"][0]["base64"]
            image_url = f"data:image/png;base64,{base64_image}"

            # Transform the response to match the structure of the other APIs
            return jsonify({"created": int(time.time()), "data": [{"url": image_url}]})

        elif model.startswith('google/'):
            # For multimodal models like Gemini, we must use a raw requests call
            # because the 'modalities' parameter is a custom OpenRouter feature
            # not supported by the official OpenAI Python library.
            headers = {
                "Authorization": f"Bearer {open_router_api_key}",
                "Content-Type": "application/json",
            }
            # For multimodal models, we inject the negative prompt into the main prompt
            full_prompt = prompt
            if negative_prompt:
                full_prompt = f"{prompt}\n\nNegative prompt: Do not include any of the following: {negative_prompt}"

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": full_prompt}],
                "modalities": ["image", "text"]
            }
            response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()

            completion = response.json()
            image_url = completion.get("choices", [{}])[0].get("message", {}).get("images", [{}])[0].get("image_url", {}).get("url")

            if not image_url:
                raise Exception("Image URL not found in OpenRouter multimodal response")

            # Transform the response to match the structure of the images.generate endpoint
            response_data = {
                "created": completion.get("created", int(time.time())),
                "data": [{"url": image_url}]
            }
            return jsonify(response_data)
        else:
            # For standard OpenRouter image models, it's more reliable to use a raw requests call
            # to ensure we can pass the recommended headers.
            headers = {
                "Authorization": f"Bearer {open_router_api_key}",
                "Content-Type": "application/json",
                # Recommended headers for OpenRouter
                "HTTP-Referer": os.environ.get('OPENROUTER_REFERER', ''),
                "X-Title": os.environ.get('OPENROUTER_TITLE', 'AI Card Gen')
            }
            payload = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024"
            }
            # Add negative prompt if it exists
            if negative_prompt:
                payload['negative_prompt'] = negative_prompt

            response = requests.post("https://openrouter.ai/api/v1/images/generations", headers=headers, json=payload)
            response.raise_for_status()

            completion = response.json()
            image_url = completion.get("data", [{}])[0].get("url")

            if not image_url:
                raise Exception("Image URL not found in OpenRouter image response")

            # The response is already in the correct format, so we can return it directly.
            return jsonify(completion)

    except requests.exceptions.RequestException as e:
        logging.error(f"Error calling an external API with requests: {e}")
        return jsonify({'error': f'Failed to communicate with an external API: {e}'}), 502
    except APIError as e:
        logging.error(f"OpenRouter API Error for image generation: {e.status_code} - {e.response}")
        return jsonify({'error': f'Image generation failed: {e.message}'}), e.status_code or 502
    except Exception as e:
        logging.error(f"An unexpected error occurred in image generation: {e}")
        return jsonify({'error': 'An unexpected server error occurred during image generation.'}), 500

@app.route('/api/save-card', methods=['POST'])
@protected_route
def save_card(decoded_token):
    """
    Saves a generated card to the Firebase Realtime Database.
    """
    try:
        card_data = request.get_json()

        if not card_data or 'imageUrl' not in card_data:
            return jsonify({'error': 'No card data or image URL provided.'}), 400

        user_id = decoded_token['uid']

        # Get a reference to the user's specific 'cards' node in the database
        ref = db.reference(f'users/{user_id}/cards')
        # Push the new card data, which generates a unique key
        new_card_ref = ref.push(card_data)

        logging.info(f"Card saved successfully with key: {new_card_ref.key}")
        return jsonify({'success': True, 'message': 'Card saved successfully!', 'cardId': new_card_ref.key}), 201

    except Exception as e:
        logging.error(f"An unexpected error occurred while saving the card: {e}")
        return jsonify({'error': 'An unexpected server error occurred while saving the card.'}), 500

@app.route('/api/search-cards', methods=['GET'])
@protected_route
def search_cards(decoded_token):
    """
    Searches for saved cards in the Firebase Realtime Database by name.
    """
    try:
        # Allow an empty query to fetch all cards for the deck builder
        query = request.args.get('q', '').strip().lower()
        user_id = decoded_token['uid']

        ref = db.reference(f'users/{user_id}/cards')
        all_cards = ref.get()

        if not all_cards:
            return jsonify([]), 200 # Return empty list if no cards exist

        search_results = []
        for card_id, card_data in all_cards.items():
            # Simple case-insensitive search in cardName
            if not query or query in card_data.get('cardName', '').lower():
                card_data['id'] = card_id # Add the unique ID to the result
                search_results.append(card_data)

        return jsonify(search_results), 200

    except Exception as e:
        logging.error(f"An unexpected error occurred during card search: {e}")
        return jsonify({'error': 'An unexpected server error occurred during card search.'}), 500

# --- Game-related Endpoints ---

@app.route('/api/decks', methods=['POST'])
@protected_route
def save_deck(decoded_token):
    """Saves a user's deck to Firebase."""
    try:
        deck_data = request.get_json()
        if not deck_data or 'name' not in deck_data or 'cardIds' not in deck_data:
            return jsonify({'error': 'Invalid deck data. Must include name and cardIds.'}), 400

        user_id = decoded_token['uid']
        ref = db.reference(f'users/{user_id}/decks')
        new_deck_ref = ref.push(deck_data)

        logging.info(f"Deck '{deck_data['name']}' saved for user {user_id} with key: {new_deck_ref.key}")
        return jsonify({'success': True, 'message': 'Deck saved!', 'deckId': new_deck_ref.key}), 201

    except Exception as e:
        logging.error(f"Error saving deck: {e}")
        return jsonify({'error': 'An unexpected server error occurred while saving the deck.'}), 500

@app.route('/api/decks', methods=['GET'])
@protected_route
def get_decks(decoded_token):
    """Retrieves all decks for a user."""
    try:
        user_id = decoded_token['uid']
        ref = db.reference(f'users/{user_id}/decks')
        decks = ref.get()

        if not decks:
            return jsonify([]), 200

        # Get all cards for the user to populate deck details
        cards_ref = db.reference(f'users/{user_id}/cards')
        all_user_cards = cards_ref.get() or {}

        decks_with_details = []
        for deck_id, deck_data in decks.items():
            card_ids = deck_data.get('cardIds', [])
            # Fetch full card data for each ID in the deck
            cards_in_deck = []
            for card_id in card_ids:
                card_detail = all_user_cards.get(card_id)
                if card_detail:
                    # Make sure the card has its ID
                    card_detail['id'] = card_id
                    cards_in_deck.append(card_detail)

            decks_with_details.append({
                'id': deck_id,
                'name': deck_data.get('name', 'Unnamed Deck'),
                'cards': cards_in_deck
            })

        return jsonify(decks_with_details), 200

    except Exception as e:
        logging.error(f"Error getting decks: {e}")
        return jsonify({'error': 'An unexpected server error occurred while getting decks.'}), 500

@app.route('/api/decks/<deck_id>', methods=['DELETE'])
@protected_route
def delete_deck(decoded_token, deck_id):
    """Deletes a user's deck from Firebase."""
    user_id = decoded_token['uid']
    ref = db.reference(f'users/{user_id}/decks/{deck_id}')
    ref.delete()
    logging.info(f"Deck {deck_id} deleted for user {user_id}")
    return jsonify({'success': True, 'message': 'Deck deleted successfully.'}), 200

import random

@app.route('/api/game/start', methods=['POST'])
@protected_route
def start_game(decoded_token):
    """Initializes a new game state in Firebase."""
    try:
        user_id = decoded_token['uid']
        data = request.get_json()
        deck_id = data.get('deckId')

        if not deck_id:
            return jsonify({'error': 'deckId is required.'}), 400

        # Fetch the user's deck and cards
        deck_ref = db.reference(f'users/{user_id}/decks/{deck_id}')
        deck_data = deck_ref.get()
        if not deck_data:
            return jsonify({'error': 'Deck not found.'}), 404

        cards_ref = db.reference(f'users/{user_id}/cards')
        all_user_cards = cards_ref.get() or {}

        player1_deck = []
        for card_id in deck_data.get('cardIds', []):
            card_detail = all_user_cards.get(card_id)
            if card_detail:
                card_detail['id'] = card_id
                # Initialize currentDefense to be the same as base defense at the start of the game
                if 'stats' in card_detail and 'defense' in card_detail['stats']:
                    card_detail['currentDefense'] = card_detail['stats']['defense']
                player1_deck.append(card_detail)

        if len(player1_deck) == 0:
            return jsonify({'error': 'Cannot start a game with an empty deck.'}), 400

        # --- Initialize Game State ---
        random.shuffle(player1_deck)
        player1_hand = player1_deck[:5]
        player1_deck = player1_deck[5:]

        # --- AI Deck Creation ---
        # Create the AI's deck from a random selection of all cards the user has ever saved.
        all_cards_list = []
        for card_id, card_data in all_user_cards.items():
            card_data['id'] = card_id
            all_cards_list.append(card_data)
        
        random.shuffle(all_cards_list)

        # The AI deck will be the same size as the player's deck.
        ai_deck_size = len(deck_data.get('cardIds', []))
        player2_deck = all_cards_list[:ai_deck_size]
        # Initialize currentDefense for AI deck as well
        for card in player2_deck:
            if 'stats' in card and 'defense' in card['stats']:
                card['currentDefense'] = card['stats']['defense']

        random.shuffle(player2_deck)
        player2_hand = player2_deck[:5]
        player2_deck = player2_deck[5:]

        game_id = str(uuid.uuid4())
        game_state = {
            "gameId": game_id,
            "status": "active",
            "turn": 1,
            "activePlayer": "player1",
            "player1": {
                "uid": user_id,
                "health": 20,
                "deck": player1_deck,
                "hand": player1_hand,
                "board": [],
                "graveyard": []
            },
            "player2": {
                "uid": "ai_opponent",
                "health": 20,
                "deck": player2_deck,
                "hand": player2_hand,
                "board": [],
                "graveyard": []
            },
        }

        # Save the initial game state to Firebase
        games_ref = db.reference(f'games/{game_id}')
        games_ref.set(game_state)

        return jsonify(game_state), 200

    except Exception as e:
        logging.error(f"An unexpected error occurred while starting the game: {e}")
        return jsonify({'error': 'An unexpected server error occurred while starting the game.'}), 500

@app.route('/api/game/<game_id>', methods=['GET'])
@protected_route
def get_game(decoded_token, game_id):
    """Retrieves the current state of a game."""
    try:
        game_ref = db.reference(f'games/{game_id}')
        game_state = game_ref.get()

        if not game_state:
            return jsonify({'error': 'Game not found.'}), 404

        # Basic authorization: Ensure the user is part of this game
        if decoded_token['uid'] != game_state.get('player1', {}).get('uid') and \
           decoded_token['uid'] != game_state.get('player2', {}).get('uid'):
            return jsonify({'error': 'You are not authorized to view this game.'}), 403

        return jsonify(game_state), 200

    except Exception as e:
        logging.error(f"Error getting game state: {e}")
        return jsonify({'error': 'An unexpected server error occurred while fetching the game.'}), 500

@app.route('/api/game/<game_id>/action', methods=['POST'])
@protected_route
def game_action(decoded_token, game_id):
    """Handles in-game actions like ending a turn."""
    try:
        user_id = decoded_token['uid']
        data = request.get_json()
        action_type = data.get('type')

        game_ref = db.reference(f'games/{game_id}')
        game_state = game_ref.get()

        if not game_state:
            return jsonify({'error': 'Game not found.'}), 404

        # Determine which player is making the action
        player_key = None
        if user_id == game_state.get('player1', {}).get('uid'):
            player_key = 'player1'
        elif user_id == game_state.get('player2', {}).get('uid'):
            player_key = 'player2'
        
        if not player_key:
            return jsonify({'error': 'You are not a player in this game.'}), 403

        if game_state['activePlayer'] != player_key:
            return jsonify({'error': 'It is not your turn.'}), 403

        if action_type == 'END_TURN':
            # --- Player's Turn Ends ---
            game_state['activePlayer'] = 'player2'
            
            # AI draws a card for its turn
            if game_state['player2'].get('deck') and len(game_state['player2']['deck']) > 0:
                new_card_for_ai = game_state['player2']['deck'].pop(0)
                if not isinstance(game_state['player2'].get('hand'), list):
                    game_state['player2']['hand'] = []
                game_state['player2']['hand'].append(new_card_for_ai)

            # --- Simple AI Turn Logic ---
            # The AI will play the first card from its hand if it has one.
            ai_hand = game_state['player2'].get('hand', [])
            if ai_hand and len(ai_hand) > 0:
                card_to_play = ai_hand.pop(0)
                if not isinstance(game_state['player2'].get('board'), list):
                    game_state['player2']['board'] = []
                game_state['player2']['board'].append(card_to_play)

            # --- AI's Turn Ends ---
            game_state['activePlayer'] = 'player1'
            game_state['turn'] += 1

            # Player draws a card for their new turn
            player_deck = game_state['player1'].get('deck', [])
            if player_deck and len(player_deck) > 0:
                new_card_for_player = player_deck.pop(0)
                if not isinstance(game_state['player1'].get('hand'), list):
                    game_state['player1']['hand'] = []
                game_state['player1']['hand'].append(new_card_for_player)

            # Update the game state in Firebase
            game_ref.set(game_state)
            return jsonify(game_state), 200


        elif action_type == 'PLAY_CARD':
            card_id = data.get('cardId')
            if not card_id:
                return jsonify({'error': 'cardId is required for PLAY_CARD action.'}), 400

            player_hand = game_state[player_key].get('hand', [])
            card_to_play = None
            card_index = -1
            for i, card in enumerate(player_hand):
                if card.get('id') == card_id:
                    card_to_play = card
                    card_index = i
                    break
            
            if not card_to_play:
                return jsonify({'error': 'Card not found in your hand.'}), 400

            # Remove card from hand
            player_hand.pop(card_index)

            # Add card to board
            if 'board' not in game_state[player_key] or not isinstance(game_state[player_key]['board'], list):
                game_state[player_key]['board'] = []
            game_state[player_key]['board'].append(card_to_play)
            
            game_ref.set(game_state)
            return jsonify(game_state), 200


        elif action_type == 'ATTACK':
            attacker_id = data.get('attackerId')
            target_id = data.get('targetId')

            if not attacker_id or not target_id:
                return jsonify({'error': 'Attacker and target IDs are required.'}), 400

            # Find attacker and target on the board
            player_board = game_state[player_key].get('board', [])
            opponent_key = 'player2' if player_key == 'player1' else 'player1'
            opponent_board = game_state[opponent_key].get('board', [])

            attacker = next((card for card in player_board if card.get('id') == attacker_id), None)
            target = next((card for card in opponent_board if card.get('id') == target_id), None)

            if not attacker:
                return jsonify({'error': 'Attacking card not found on your board.'}), 400
            if not target:
                return jsonify({'error': 'Target card not found on opponent\'s board.'}), 400

            # --- Combat Logic ---
            attacker_atk = int(attacker.get('stats', {}).get('attack', 0))
            target_atk = int(target.get('stats', {}).get('attack', 0))

            # Use currentDefense if it exists, otherwise fall back to base defense
            target_def = int(target.get('currentDefense', target.get('stats', {}).get('defense', 0)))
            attacker_def = int(attacker.get('currentDefense', attacker.get('stats', {}).get('defense', 0)))

            # Cards deal damage to each other
            target['currentDefense'] = target_def - attacker_atk
            attacker['currentDefense'] = attacker_def - target_atk

            # Check for destroyed cards
            attacker_destroyed = attacker['currentDefense'] <= 0
            target_destroyed = target['currentDefense'] <= 0

            if target_destroyed:
                # Move target from board to graveyard
                game_state[opponent_key]['board'] = [card for card in opponent_board if card.get('id') != target_id]
                if 'graveyard' not in game_state[opponent_key] or not isinstance(game_state[opponent_key]['graveyard'], list):
                    game_state[opponent_key]['graveyard'] = []
                # Remove currentDefense before moving to graveyard to reset it
                target.pop('currentDefense', None)
                game_state[opponent_key]['graveyard'].append(target)

            if attacker_destroyed:
                # Move attacker from board to graveyard
                game_state[player_key]['board'] = [card for card in player_board if card.get('id') != attacker_id]
                if 'graveyard' not in game_state[player_key] or not isinstance(game_state[player_key]['graveyard'], list):
                    game_state[player_key]['graveyard'] = []
                # Remove currentDefense before moving to graveyard to reset it
                attacker.pop('currentDefense', None)
                game_state[player_key]['graveyard'].append(attacker)

            # Update the game state in Firebase
            game_ref.set(game_state)
            return jsonify(game_state), 200

        elif action_type == 'ATTACK_PLAYER':
            attacker_id = data.get('attackerId')
            if not attacker_id:
                return jsonify({'error': 'Attacker ID is required.'}), 400

            player_board = game_state[player_key].get('board', [])
            opponent_key = 'player2' if player_key == 'player1' else 'player1'
            opponent_board = game_state[opponent_key].get('board', [])

            # Ensure opponent's board is empty
            if len(opponent_board) > 0:
                return jsonify({'error': 'Cannot attack player directly when they have cards on the board.'}), 400

            attacker = next((card for card in player_board if card.get('id') == attacker_id), None)
            if not attacker:
                return jsonify({'error': 'Attacking card not found on your board.'}), 400

            # --- Direct Damage Logic ---
            attacker_atk = int(attacker.get('stats', {}).get('attack', 0))
            opponent_health = game_state[opponent_key].get('health', 0)
            game_state[opponent_key]['health'] = opponent_health - attacker_atk

            # --- Win Condition Check ---
            if game_state[opponent_key]['health'] <= 0:
                game_state['status'] = 'finished'
                game_state['winner'] = player_key
                logging.info(f"Game {game_id} finished. Winner: {player_key}")

            # Update the game state in Firebase
            game_ref.set(game_state)
            return jsonify(game_state), 200


        else:
            return jsonify({'error': 'Invalid action type.'}), 400

    except Exception as e:
        logging.error(f"Error during game action: {e}")
        return jsonify({'error': 'An unexpected server error occurred during the game action.'}), 500


if __name__ == '__main__':
    # Use the PORT environment variable if available, otherwise default to 3000
    port = int(os.environ.get('PORT', 3000))
    # Listen on all network interfaces.
    # The reloader has to be disabled because it will not work in this environment.
    app.run(host='0.0.0.0', port=port, debug=True)
