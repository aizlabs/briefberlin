# Local Jekyll Setup

The static site lives in `output/`.

```bash
cd output
bundle install
bundle exec jekyll serve
```

Only generated public German posts should live in `output/_posts/`. Keep manual source articles in ignored private input paths.
