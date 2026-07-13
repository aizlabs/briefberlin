---
permalink: /authors/
title: "Authors"
excerpt: "BriefBerlin writers and editors"
layout: single
---

<div class="authors-directory">
{% for author_entry in site.data.authors %}
  {% assign profile = author_entry[1] %}
  <article class="author-card">
    <a class="author-card__image" href="{{ profile.url | relative_url }}">
      <img src="{{ profile.image | relative_url }}" alt="{{ profile.image_alt | default: profile.name }}">
    </a>
    <div>
      <h2><a href="{{ profile.url | relative_url }}">{{ profile.name }}</a></h2>
      <p class="author-card__role">{{ profile.role }}</p>
      <p>{{ profile.bio }}</p>
    </div>
  </article>
{% endfor %}
</div>
