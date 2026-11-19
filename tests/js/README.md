# Meine Wörter JavaScript tests

Run commands from the repository root. Unit tests use Node's built-in runner and need no packages (Node 20 or newer):

```sh
node --test tests/js/*.test.cjs
```

Browser tests use Playwright as a development-only dependency. Install it into a temporary tooling directory, not the published site:

```sh
npm install --prefix /tmp/briefberlin-browser-tests playwright
NODE_PATH=/tmp/briefberlin-browser-tests/node_modules /tmp/briefberlin-browser-tests/node_modules/.bin/playwright install chromium
NODE_PATH=/tmp/briefberlin-browser-tests/node_modules node --test tests/js/*.browser.cjs
```

Set `PLAYWRIGHT_EXECUTABLE_PATH` to an existing Chromium/headless-shell executable if needed. Tests launch an isolated browser and loopback-only fixture servers; they never use personal browser profiles. They require an environment that permits local server sockets and browser processes.

For the integrated suite, build Jekyll first and point to its output:

```sh
cd output
bundle exec jekyll build --destination /tmp/briefberlin-my-words-site
cd ..
BRIEFBERLIN_SITE_DIR=/tmp/briefberlin-my-words-site NODE_PATH=/tmp/briefberlin-browser-tests/node_modules node --test tests/js/my-words-site.browser.cjs
```

The built-site suite is skipped if `BRIEFBERLIN_SITE_DIR` is absent. Set `BRIEFBERLIN_SCREENSHOT_DIR` to save desktop/mobile screenshots outside the site. All other browser fixtures load production JavaScript and page markup directly from the repository, without a Jekyll build.

Optional real Anki import verification uses Anki's official Python package in an isolated environment:

```sh
python3 -m venv /tmp/briefberlin-anki-check
/tmp/briefberlin-anki-check/bin/python -m pip install anki
/tmp/briefberlin-anki-check/bin/python tests/manual/check_my_words_anki.py
```

This generates synthetic vocabulary with the production serializer, imports it into a temporary collection, and checks a second import does not duplicate notes/cards. It never opens personal Anki collections. No Anki dependency is added to the application.
