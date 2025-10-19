# 🤖 Telegram AI Bot Runner

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-green.svg)](LICENSE)
[![OpenAI Compatible](https://img.shields.io/badge/LLM-OpenAI-blue)](#)
[![xAI Compatible](https://img.shields.io/badge/LLM-xAI-black)](#)

**Configurable, LLM-powered Telegram bot runner with multi-provider support.**

## ⚡️ Key Features

| 🧩 Feature | ⚙️ Description |
|---|---|
| **Multi-Bot Support** | Each bot lives in its own folder with associated **config** and **identity** files. |
| **Configurable Models** | Backend for **LLM**, **Vision**, and **Embedding** models are individually configurable. |
| **Reply Triggers** | Bot replies when **mentioned** in groups, in **1:1 DMs**, or when users **reply to the bot**. |
| **Markdown Support** | Automatically converts and escapes LLM output for proper **Telegram Markdown** rendering. |
| **Vision-Aware** | Runs **vision analysis** on incoming image messages, then stores descriptions. |
| **Smart Reactions** | LLM returns an emoji + **reaction_strength**; bot reacts only when ≥ **`reaction_threshold`**. |
| **RAG Memory** | Embeds messages and performs **vector search** to retrieve relevant history. |
| **Access Gate** | New users must be **approved by the admin** via inline **Yes/No** buttons. |
| **Error Alerts** | A custom log handler forwards **ERROR** logs directly to the **admin chat**. |
| **Config Autocomplete** | **VS Code** offers **autocomplete & validation** for json config files. |

## Prerequisites
- A **Telegram bot token** created via [@BotFather](https://t.me/BotFather)
- Your personal **Telegram user ID** (send a message to [@userinfobot](https://t.me/userinfobot) to view)
- An **API key** for at least one of the supported LLMs
- **Visual Studio Code** — for bot configuration autocomplete and debugging

## Initial Setup

1. **Create and activate a virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

## Configuring a Bot

1. Create a folder for the bot inside the `bots` folder

   Folder name can be the bot's first name, username or anything else, as long as its unique to other bots you create.  

   However, you may want to make this short and memorable, if you plan on starting the bot via command line.  

2. Inside of the bot folder, create `config.json`

   If you’re using VS Code, it will provide autocomplete suggestions and validation warnings for missing or invalid fields.

   Validation schema lives in `config.schema.json`

   Example bot config using OpenAI:

   ```json
   {
      "telegram_token": "YOUR_TELEGRAM_TOKEN",
      "admin_user_id": 123456789,
      "context_window": "4h",
      "reaction_threshold": 0.6,
      "llm": {
         "openai": {
               "api_key": "YOUR_OPENAI_API_KEY",
               "model": "gpt-5-2025-08-07"
         }
      },
      "vision": {
         "openai": {
               "api_key": "YOUR_OPENAI_API_KEY",
               "model": "gpt-5-2025-08-07"
         }
      },
      "rag": {
         "limit": 10,
         "embedding": {
               "openai": {
                  "api_key": "YOUR_OPENAI_API_KEY",
                  "model": "text-embedding-3-small",
                  "dimensions": 1536
               }
         }
      }
   }
   ```

3. Inside of the bot folder, create identity.txt

   The text in this file will be sent as a system message for every LLM request.

   Use it to define how you want your bot to behave, and if you want it to be human-like, it's identity/background.  

## Running a Bot

```bash
python3 run.py {BOT_FOLDER_NAME}
```

## Debugging a Bot

1. Create a `.vscode/launch.json` file in your workspace.

2. Add a bot configuration entry:

   ```json
   {
      "name": "Run BOT_FOLDER_NAME",
      "type": "debugpy",
      "request": "launch",
      "program": "${workspaceFolder}/run.py",
      "console": "integratedTerminal",
      "python": "${workspaceFolder}/.venv/bin/python",
      "args": ["BOT_FOLDER_NAME"],
      "env": {
         "LOG_CONSOLE_LEVEL": "DEBUG"
      }
   }
   ```

3. In VS Code, select your configuration from the Run and Debug panel (or press F5) to start debugging.
