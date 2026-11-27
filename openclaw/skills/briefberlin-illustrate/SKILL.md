---
name: briefberlin-illustrate
description: Add one illustration to the waiting BriefBerlin story before its preview. Used by the briefberlin skill after `bb generate` prints READY; not for anything else.
---

# BriefBerlin illustration (bot)

Use only `/workspace/skills/briefberlin-suite/briefberlin/scripts/bb`. Do not use the `image_generate` tool: its result arrives in a turn that cannot run `bb`. Do not run git, edit the repo, or read the inbox source: the picture must come from the public article text alone.

1. Run `bb stories`. It prints the story id and the final A2 and B1 text. Read the headline, summary and body.
2. Choose **one illustration** for the story. Pick a subject and action an A2 reader would recognise. Keep the story's distinctions: a proposal is not a decision, a suspicion is not a conviction.
   - Choose a medium, light and palette that fit this story. Quiet grey graphite can suit mourning, colourful watercolour a public space, a photorealistic scene an everyday object or service. Take colour from the subject.
   - Show no lettering, signs with words, logos, brand names or party symbols, and no invented documentary details.
   - Do not make portraits of real, named people. Show the situation instead, with people seen from behind, at a distance or as hands, so nobody is identifiable.
   - If the story is mainly numbers, still choose a scene; charts are made separately.
3. Run `bb illustrate <story> "<prompt>" "<alt>"` once. It generates the picture with OpenAI gpt-image-2 (medium quality, 1280x720 WebP), checks it and attaches it; this takes about a minute.
   - `<prompt>`: English, describing the scene, medium and light, ending with "No text, no logos."
   - `<alt>`: one plain German sentence describing what the picture shows, for example "Eine Pflegekraft steckt einen Stimmzettel in eine rote Box."
4. It prints `IMAGE ADDED` on success. If it prints ERROR, run it once more with a corrected prompt; after a second ERROR continue without a picture: the article stays publishable.
5. Report to the user in English (one short line), never in German. Do not send the image to the chat yourself; `bb preview` sends it with the articles.
