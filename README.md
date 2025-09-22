# AI Card Generator

This web application allows you to generate unique trading card concepts and images using AI. Powered by Flask, OpenRouter, and DeepAI, you can design cards with custom names, types, descriptions, and abilities, and then bring them to life with AI-generated art.

## Features

-   Generate detailed card concepts, including lore, stats, and abilities.
-   Generate four unique artistic variations for each card concept.
-   Choose from multiple image generation models (e.g., Stable Diffusion 3, DeepAI Fantasy World).
-   Expand card lore and get synergy suggestions for your creations.
-   Export individual cards as high-quality PNGs or download a full set as a ZIP file.
-   Save and view your generation history directly in the browser.

## Prerequisites

-   Python 3.8+
-   pip

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3.  **Install the dependencies:**
    The required packages are listed in `requirements.txt` and can be installed with pip.
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

The application requires API keys for the AI services it uses to generate content.

1.  **Create a `.env` file:**
    Copy the example environment file to create your own local configuration file.
    ```bash
    cp .env.example .env
    ```

2.  **Edit the `.env` file:**
    Open the newly created `.env` file and add your secret API keys:
    ```
    # Get your key from https://openrouter.ai/keys
    OPENROUTER_API_KEY="sk-or-..."

    # Get your key from https://deepai.org/
    DEEPAI_API_KEY="your-deepai-api-key"

    # Optional: For OpenRouter integration, you can set your site URL and app title.
    # This helps identify your app on the OpenRouter dashboard.
    # See https://openrouter.ai/docs#headers for more info.
    # OPENROUTER_REFERER=https://your-site.com
    # OPENROUTER_TITLE=AI Card Gen
    ```

## Running the Application

### For Production (with Gunicorn)

Gunicorn is included in the requirements and is the recommended way to run the application for a demo or public use.

```bash
gunicorn --bind 0.0.0.0:3000 app:app
```
The application will then be available at `http://localhost:3000`.

### For Development (with Flask's built-in server)

For development purposes, you can run the application directly using Flask's built-in server.

```bash
python app.py
```
The application will be available at `http://localhost:3000`. The port can be changed by setting the `PORT` environment variable in your `.env` file.
