# Project Overview

This project, "AutoSpanishBlog," is an automated pipeline that generates Spanish language learning articles. It discovers newsworthy topics from various sources, fetches the content, generates a new article, checks its quality, and then publishes it to a Jekyll-based blog.

**Main Technologies:**

*   **Backend:** Python 3.11, uv, SpaCy, trafilatura, OpenAI GPT-4o
*   **Frontend:** Jekyll
*   **Automation:** GitHub Actions
*   **Containerization:** Docker

**Architecture:**

The project follows a pipeline architecture orchestrated by `scripts/main.py`. The pipeline consists of the following stages:

1.  **Topic Discovery:** Identifies newsworthy topics from over 20 sources.
2.  **Content Fetching:** Downloads and cleans text from source articles.
3.  **Content Generation:** Synthesizes a new article from the fetched content.
4.  **Quality Gate:** Checks the quality of the generated article.
5.  **Publishing:** Saves the article as a Jekyll blog post.

# Building and Running

**Installation:**

1.  Install dependencies:
    ```bash
    uv sync
    ```

2.  Configure API keys:
    ```bash
    cp .env.example .env
    # Edit .env and add your OPENAI_API_KEY
    ```

**Running the Pipeline:**

*   **Full Pipeline:**
    ```bash
    uv run spai-pipeline
    ```

*   **Individual Components:**
    ```bash
    uv run spai-discover
    uv run spai-fetch
    uv run spai-generate
    ```

**Testing:**

*   Run all tests:
    ```bash
    pytest
    ```

# Development Conventions

*   **Linting:** The project uses `ruff` for linting.
*   **Testing:** Tests are located in the `tests/` directory and are written using `pytest`.
*   **Configuration:** The project uses YAML files for configuration, located in the `config/` directory.
*   **Dependencies:** Python dependencies are managed with `uv` and defined in `pyproject.toml`.
