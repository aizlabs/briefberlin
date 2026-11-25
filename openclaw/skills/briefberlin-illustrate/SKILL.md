---
name: briefberlin-illustrate
description: Add one illustration to the waiting BriefBerlin story before its preview. Used by the briefberlin skill after `bb generate` prints READY; not for anything else.
---

# BriefBerlin illustration (bot)

Use only `/opt/openclaw/.openclaw/workspace/skills/briefberlin/scripts/bb` and the `image_generate` tool. Do not run git, edit the repo, or read the inbox source: the picture must come from the public article text alone.

1. Run `bb stories`. It prints the story id and the final A2 and B1 text. Read the headline, summary and body.
2. Choose **one illustration** for the story. Pick a subject and action an A2 reader would recognise. Keep the story's distinctions: a proposal is not a decision, a suspicion is not a conviction.
   - Choose a medium, light and palette that fit this story. Quiet grey graphite can suit mourning, colourful watercolour a public space, a photorealistic scene an everyday object or service. Take colour from the subject.
   - Show no lettering, signs with words, logos, brand names or party symbols, and no invented documentary details.
   - Do not make portraits of real, named people. Show the situation instead, with people seen from behind, at a distance or as hands, so nobody is identifiable.
   - If the story is mainly numbers, still choose a scene; charts are made separately.
3. Call `image_generate` once with: `size: "1280x720"`, `quality: "medium"`, `outputFormat: "webp"`, `count: 1`, and `openai: {"outputCompression": 80}`. Write the prompt in English, describing the scene, medium and light, and end it with "No text, no logos."
4. The image arrives later as a background-task result with a file path. Then run:
   `bb add-image <story> <file path> "<alt>"`
   where `<alt>` is one plain German sentence describing what the picture shows, for example "Eine Pflegekraft steckt einen Stimmzettel in eine rote Box."
5. If the image shows text, a logo, a recognisable face of a real person or something the story does not say, generate it once more with a corrected prompt. If the tool fails or `bb add-image` prints ERROR twice, continue without a picture: the article stays publishable.
6. Do not send the image to the chat yourself; `bb preview` sends it with the articles.
